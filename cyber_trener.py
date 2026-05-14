import cv2
import mediapipe as mp
import numpy as np
import pyttsx3
import threading
import time


class BulgarianSquatTrainer:
    def __init__(self):
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_pose = mp.solutions.pose
        
        # Nowy, niezawodny system blokady mowy (zastępuje awaryjną kolejkę Queue)
        self.speech_lock = threading.Lock()
        
        self.state = "POWITANIE"
        self.counter = 0
        self.current_rep_valid = True
        
        self.errors_this_rep = set() 
        self.last_feedback_time = 0
        self.is_greeting_done = False
        self.start_time = time.time()

        self.angle_up = 140    
        self.angle_down = 110  

        self.trening_log = []
        self.smoothed_landmarks = {}
        self.alpha = 0.5 

    def speak(self, text, force=False):
        # Jeśli lektor nic nie mówi (lub wymuszamy komunikat)
        if not self.speech_lock.locked() or force:
            print(f"[TRENER MÓWI]: {text}") 
            # Odpalamy całkowicie oddzielny wątek dla każdego zdania
            threading.Thread(target=self._speak_task, args=(text,), daemon=True).start()

    def _speak_task(self, text):
        # Ten lock sprawia, że jeśli program ma do powiedzenia 2 zdania na raz, to poczeka i powie je po kolei
        with self.speech_lock:
            # 1. PRÓBA BEZPOŚREDNIA WINDOWS SAPI (Zupełnie omija błędy pyttsx3 zawieszającego się przez kamerę)
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize() 
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Rate = 2 # Tempo od -10 do 10
                speaker.Speak(text)
                return # Sukces, kończymy wątek
            except Exception:
                pass # Jeśli to nie Windows, idzie dalej do opcji awaryjnej
            
            # 2. OPCJA AWARYJNA (Linux/Mac)
            try:
                engine = pyttsx3.init()
                engine.setProperty('rate', 170)
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                print(f"Błąd awaryjnego systemu TTS: {e}")

    @staticmethod
    def calculate_angle(a, b, c):
        a = np.array(a)
        b = np.array(b)
        c = np.array(c)
        radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
        angle = np.abs(radians * 180.0 / np.pi)
        if angle > 180.0:
            angle = 360 - angle
        return angle

    def smooth_landmark(self, name, current_pt, side):
        key = f"{side}_{name}"
        if key not in self.smoothed_landmarks:
            self.smoothed_landmarks[key] = current_pt
        else:
            self.smoothed_landmarks[key] = [
                self.alpha * current_pt[0] + (1 - self.alpha) * self.smoothed_landmarks[key][0],
                self.alpha * current_pt[1] + (1 - self.alpha) * self.smoothed_landmarks[key][1]
            ]
        return self.smoothed_landmarks[key]

    def calculate_torso_lean(self, shoulder, hip):
        vertical_pt = [hip[0], hip[1] - 100.0]
        return self.calculate_angle(shoulder, hip, vertical_pt)

    def run(self):
        cap = cv2.VideoCapture(0)  

        with self.mp_pose.Pose(min_detection_confidence=0.5,
                               min_tracking_confidence=0.7,
                               model_complexity=1) as pose:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                frame = cv2.flip(frame, 1)
                image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image.flags.writeable = False
                results = pose.process(image)
                image.flags.writeable = True
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

                progress_val = 0
                ui_error_msg = None 
                h, w, _ = image.shape
                aktywna_noga = "BRAK"

                if results.pose_landmarks:
                    try:
                        landmarks = results.pose_landmarks.landmark

                        left_ankle_lm = landmarks[self.mp_pose.PoseLandmark.LEFT_ANKLE.value]
                        right_ankle_lm = landmarks[self.mp_pose.PoseLandmark.RIGHT_ANKLE.value]

                        # Obliczanie koordynatów
                        if right_ankle_lm.y > left_ankle_lm.y:
                            aktywna_noga = "PRAWA NOGA"
                            if landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value].visibility < 0.4 or \
                                    landmarks[self.mp_pose.PoseLandmark.RIGHT_KNEE.value].visibility < 0.4:
                                raise ValueError("slaba_widocznosc")

                            raw_shoulder = [landmarks[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value].x * w,
                                            landmarks[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value].y * h]
                            raw_hip = [landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value].x * w,
                                       landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value].y * h]
                            raw_knee = [landmarks[self.mp_pose.PoseLandmark.RIGHT_KNEE.value].x * w,
                                        landmarks[self.mp_pose.PoseLandmark.RIGHT_KNEE.value].y * h]
                            raw_ankle = [landmarks[self.mp_pose.PoseLandmark.RIGHT_ANKLE.value].x * w,
                                         landmarks[self.mp_pose.PoseLandmark.RIGHT_ANKLE.value].y * h]
                        else:
                            aktywna_noga = "LEWA NOGA"
                            if landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value].visibility < 0.4 or \
                                    landmarks[self.mp_pose.PoseLandmark.LEFT_KNEE.value].visibility < 0.4:
                                raise ValueError("slaba_widocznosc")

                            raw_shoulder = [landmarks[self.mp_pose.PoseLandmark.LEFT_SHOULDER.value].x * w,
                                            landmarks[self.mp_pose.PoseLandmark.LEFT_SHOULDER.value].y * h]
                            raw_hip = [landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value].x * w,
                                       landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value].y * h]
                            raw_knee = [landmarks[self.mp_pose.PoseLandmark.LEFT_KNEE.value].x * w,
                                        landmarks[self.mp_pose.PoseLandmark.LEFT_KNEE.value].y * h]
                            raw_ankle = [landmarks[self.mp_pose.PoseLandmark.LEFT_ANKLE.value].x * w,
                                         landmarks[self.mp_pose.PoseLandmark.LEFT_ANKLE.value].y * h]

                        shoulder = self.smooth_landmark("shoulder", raw_shoulder, aktywna_noga)
                        hip = self.smooth_landmark("hip", raw_hip, aktywna_noga)
                        knee = self.smooth_landmark("knee", raw_knee, aktywna_noga)
                        ankle = self.smooth_landmark("ankle", raw_ankle, aktywna_noga)

                        knee_angle = self.calculate_angle(hip, knee, ankle)
                        torso_lean_angle = self.calculate_torso_lean(shoulder, hip)

                        progress_val = np.interp(knee_angle, [self.angle_down, self.angle_up], [100, 0])

                        if self.state not in ["POWITANIE", "GORA"]:
                            # Opad tułowia (garbienie się)
                            if torso_lean_angle > 40.0:
                                self.current_rep_valid = False
                                self.errors_this_rep.add("Wyprostuj plecy!")
                                ui_error_msg = "Wyprostuj plecy!" 

                        # --- LOGIKA RUCHU ---
                        if self.state == "POWITANIE":
                            if time.time() - self.start_time > 3.0 and not self.is_greeting_done:
                                self.speak("Czesc! Ustaw sie do przysiadu bulgarskiego. Zaczynamy!", force=True)
                                self.is_greeting_done = True
                                self.state = "GORA"
                                
                        elif self.state == "GORA":
                            if knee_angle < self.angle_up - 10:
                                self.state = "W_DOL"
                                
                        elif self.state == "W_DOL":
                            if knee_angle <= self.angle_down:
                                self.state = "DOL"
                            elif knee_angle >= self.angle_up + 5:
                                blad_msg = " ".join(self.errors_this_rep)
                                self.speak(f"Niepelny przysiad! {blad_msg}", force=True)
                                self.state = "GORA"
                                self.current_rep_valid = True
                                self.errors_this_rep.clear()
                                
                        elif self.state == "DOL":
                            if knee_angle > self.angle_down + 10:
                                self.state = "W_GORE"
                                
                        elif self.state == "W_GORE":
                            if knee_angle >= self.angle_up:
                                # Koniec powtórzenia - OCENA RUCHU
                                if self.current_rep_valid:
                                    self.counter += 1
                                    self.speak(f"Pieknie, {self.counter}", force=True)
                                    self.trening_log.append(f"Poprawne powtorzenie nr {self.counter} o {time.strftime('%H:%M:%S')}")
                                else:
                                    blad_msg = " ".join(self.errors_this_rep)
                                    self.speak(f"Spalone. {blad_msg}", force=True)
                                
                                self.current_rep_valid = True
                                self.errors_this_rep.clear()
                                self.state = "GORA"
                                
                            elif knee_angle < self.angle_down + 5:
                                self.speak("Zepsuty ruch!", force=True)
                                self.current_rep_valid = True
                                self.errors_this_rep.clear()
                                self.state = "DOL"

                    except ValueError as e:
                        if str(e) == "slaba_widocznosc":
                            ui_error_msg = "BRAK NOGI W KADRZE!"
                    except Exception as e:
                        pass

                self.mp_drawing.draw_landmarks(image, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)

                cv2.rectangle(image, (0, 0), (300, 73), (245, 117, 16), -1)
                cv2.putText(image, 'POWTORZENIA', (15, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(image, str(self.counter), (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(image, 'FAZA RUCHU', (150, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(image, self.state, (150, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

                cv2.putText(image, 'CYBER-TRENER', (w - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(image, f'SLEDZONA: {aktywna_noga}', (w - 230, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

                if ui_error_msg:
                    cv2.putText(image, ui_error_msg, (15, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)

                bar_x = w - 60
                bar_y_start = int(h * 0.2)
                bar_y_end = int(h * 0.8)
                bar_max_height = bar_y_end - bar_y_start

                cv2.rectangle(image, (bar_x, bar_y_start), (bar_x + 30, bar_y_end), (50, 50, 50), -1)
                cv2.rectangle(image, (bar_x, bar_y_start), (bar_x + 30, bar_y_end), (255, 255, 255), 2)

                fill_height = int(bar_max_height * (progress_val / 100.0))
                bar_color = (0, 0, 255) if not self.current_rep_valid else (0, 255, 0)
                fill_height = max(0, min(fill_height, bar_max_height))

                cv2.rectangle(image, (bar_x, bar_y_end - fill_height), (bar_x + 30, bar_y_end), bar_color, -1)
                cv2.putText(image, f"{int(progress_val)}%", (bar_x - 50, bar_y_end - fill_height + 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                cv2.imshow('Cyber Trener - Bulgarski Przysiad', image)

                if cv2.waitKey(10) & 0xFF == ord('q'):
                    break

        if self.counter > 0:
            with open("historia_treningow.txt", "a") as f:
                f.write(f"\n--- Trening z dnia {time.strftime('%Y-%m-%d')} ---\n")
                for wpis in self.trening_log:
                    f.write(wpis + "\n")
                f.write(f"Zakonczono z wynikiem: {self.counter} powtorzen.\n")

        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    trainer = BulgarianSquatTrainer()
    trainer.run()
