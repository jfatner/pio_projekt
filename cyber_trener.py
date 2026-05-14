import cv2
import mediapipe as mp
import numpy as np
import pyttsx3
import threading
import time
import queue
import math


class BulgarianSquatTrainer:
    def __init__(self):
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_pose = mp.solutions.pose
        self.tts_queue = queue.Queue()
        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()
        self.state = "POWITANIE"
        self.counter = 0
        self.current_rep_valid = True
        self.last_feedback_time = 0
        self.feedback_cooldown = 1.5
        self.is_greeting_done = False
        self.start_time = time.time()

        # Płytszy przysiad (110 stopni) dla łatwiejszego zaliczenia ruchu
        self.angle_up = 160
        self.angle_down = 110

        self.trening_log = []

        # Inicjalizacja słownika do wygładzania ruchów (EMA filter)
        self.smoothed_landmarks = {}
        self.alpha = 0.5  # Współczynnik wygładzania (0.1 - bardzo powolne, 0.9 - bardzo szybkie)

    def _tts_worker(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass
        engine = pyttsx3.init()
        engine.setProperty('rate', 160)
        while True:
            text = self.tts_queue.get()
            if text is None:
                break
            engine.say(text)
            engine.runAndWait()
            self.tts_queue.task_done()

    def speak(self, text, force=False):
        if self.tts_queue.empty() or force:
            self.tts_queue.put(text)

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

    # Funkcja wygładzająca trzęsące się punkty (Exponential Moving Average)
    def smooth_landmark(self, name, current_pt):
        if name not in self.smoothed_landmarks:
            self.smoothed_landmarks[name] = current_pt
        else:
            self.smoothed_landmarks[name] = [
                self.alpha * current_pt[0] + (1 - self.alpha) * self.smoothed_landmarks[name][0],
                self.alpha * current_pt[1] + (1 - self.alpha) * self.smoothed_landmarks[name][1]
            ]
        return self.smoothed_landmarks[name]

    def calculate_torso_lean(self, shoulder, hip):
        vertical_pt = [hip[0], hip[1] - 1.0]
        return self.calculate_angle(shoulder, hip, vertical_pt)

    def run(self):
        cap = cv2.VideoCapture(0)  # 1 - kamera zewnetrzna 0 - wbudowana

        # ZWIĘKSZONA PEWNOŚĆ MODELU:
        # min_tracking_confidence na 0.7 (zapobiega gubieniu kończyn przy dziwnych pozach)
        # model_complexity=1 (możesz zmienić na 2, jeśli masz bardzo mocny komputer i nadal będzie gubić punkty)
        with self.mp_pose.Pose(min_detection_confidence=0.5,
                               min_tracking_confidence=0.7,
                               model_complexity=1) as pose:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                # Odbicie lustrzane obrazu w poziomie
                frame = cv2.flip(frame, 1)

                image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image.flags.writeable = False
                results = pose.process(image)
                image.flags.writeable = True
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

                progress_val = 0
                current_error_msg = None
                h, w, _ = image.shape
                aktywna_noga = "BRAK"

                if results.pose_landmarks:
                    try:
                        landmarks = results.pose_landmarks.landmark

                        # Sprawdzenie orientacji ciała
                        left_hip = landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value]
                        right_hip = landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value]

                        # Wybór odpowiednich punktów w zależności od tego, którym bokiem stoimy do kamery
                        if right_hip.z < left_hip.z:
                            aktywna_noga = "PRAWA NOGA"
                            # Weryfikacja widoczności - zapobiega błędom, gdy obiektyw nie widzi np. stopy
                            if landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value].visibility < 0.4 or \
                                    landmarks[self.mp_pose.PoseLandmark.RIGHT_KNEE.value].visibility < 0.4:
                                raise ValueError("Punkty slabo widoczne")

                            raw_shoulder = [landmarks[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value].x,
                                            landmarks[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value].y]
                            raw_hip = [landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value].x,
                                       landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value].y]
                            raw_knee = [landmarks[self.mp_pose.PoseLandmark.RIGHT_KNEE.value].x,
                                        landmarks[self.mp_pose.PoseLandmark.RIGHT_KNEE.value].y]
                            raw_ankle = [landmarks[self.mp_pose.PoseLandmark.RIGHT_ANKLE.value].x,
                                         landmarks[self.mp_pose.PoseLandmark.RIGHT_ANKLE.value].y]
                        else:
                            aktywna_noga = "LEWA NOGA"
                            if landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value].visibility < 0.4 or \
                                    landmarks[self.mp_pose.PoseLandmark.LEFT_KNEE.value].visibility < 0.4:
                                raise ValueError("Punkty slabo widoczne")

                            raw_shoulder = [landmarks[self.mp_pose.PoseLandmark.LEFT_SHOULDER.value].x,
                                            landmarks[self.mp_pose.PoseLandmark.LEFT_SHOULDER.value].y]
                            raw_hip = [landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value].x,
                                       landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value].y]
                            raw_knee = [landmarks[self.mp_pose.PoseLandmark.LEFT_KNEE.value].x,
                                        landmarks[self.mp_pose.PoseLandmark.LEFT_KNEE.value].y]
                            raw_ankle = [landmarks[self.mp_pose.PoseLandmark.LEFT_ANKLE.value].x,
                                         landmarks[self.mp_pose.PoseLandmark.LEFT_ANKLE.value].y]

                        # Przepuszczenie punktów przez filtr wygładzający (likwidacja drgań kamery/modelu)
                        shoulder = self.smooth_landmark("shoulder", raw_shoulder)
                        hip = self.smooth_landmark("hip", raw_hip)
                        knee = self.smooth_landmark("knee", raw_knee)
                        ankle = self.smooth_landmark("ankle", raw_ankle)

                        knee_angle = self.calculate_angle(hip, knee, ankle)
                        torso_lean_angle = self.calculate_torso_lean(shoulder, hip)

                        progress_val = np.interp(knee_angle, [self.angle_down, self.angle_up], [100, 0])

                        if self.state != "POWITANIE":
                            # USUNĘLIŚMY restrykcje dla kolana - zostawiamy tylko skrajny opad tułowia (powyżej 75 stopni!)
                            if torso_lean_angle > 75.0:
                                current_error_msg = "Wyprostuj plecy!"

                        if current_error_msg:
                            self.current_rep_valid = False
                            current_time = time.time()
                            if current_time - self.last_feedback_time > self.feedback_cooldown:
                                self.speak(current_error_msg)
                                self.last_feedback_time = current_time

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
                                if self.current_rep_valid:
                                    self.speak("Dobry dol, teraz w gore!")
                            elif knee_angle > self.angle_up:
                                self.state = "GORA"
                        elif self.state == "DOL":
                            if knee_angle > self.angle_down + 10:
                                self.state = "W_GORE"
                        elif self.state == "W_GORE":
                            if knee_angle >= self.angle_up:
                                if self.current_rep_valid:
                                    self.counter += 1
                                    self.speak(f"Pieknie, {self.counter}")
                                    self.trening_log.append(
                                        f"Poprawne powtorzenie nr {self.counter} o {time.strftime('%H:%M:%S')}")
                                else:
                                    self.speak("Powtorzenie spalone. Skup sie i zacznij jeszcze raz.")
                                self.current_rep_valid = True
                                self.state = "GORA"

                    except ValueError:
                        # Przechwytuje moment, gdy kamera źle nas widzi - ignoruje klatkę bez niszczenia wyniku
                        pass
                    except Exception as e:
                        print(e)
                        pass

                self.mp_drawing.draw_landmarks(image, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)

                cv2.rectangle(image, (0, 0), (300, 73), (245, 117, 16), -1)
                cv2.putText(image, 'POWTORZENIA', (15, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(image, str(self.counter), (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 2,
                            cv2.LINE_AA)
                cv2.putText(image, 'FAZA RUCHU', (150, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(image, self.state, (150, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
                            cv2.LINE_AA)

                cv2.putText(image, 'CYBER-TRENER', (w - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
                            cv2.LINE_AA)
                cv2.putText(image, f'SLEDZONA: {aktywna_noga}', (w - 200, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (0, 255, 0), 1, cv2.LINE_AA)

                if current_error_msg:
                    cv2.putText(image, current_error_msg, (15, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2,
                                cv2.LINE_AA)

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

        self.tts_queue.put(None)
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    trainer = BulgarianSquatTrainer()
    trainer.run()
