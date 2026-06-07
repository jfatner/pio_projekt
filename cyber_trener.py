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

        self.speech_lock = threading.Lock()

        # Nowe stany dla gestów
        self.state = "CZEKA NA START"
        self.counter = 0
        self.current_rep_valid = True

        self.errors_this_rep = set()
        self.is_greeting_done = False

        # Timery do trzymania gestów przez 2 sekundy
        self.gesture_hold_time = 2.0
        self.start_pose_timer = 0
        self.stop_pose_timer = 0
        self.start_time = 0

        # Dynamiczne progi (zostaną nadpisane podczas kalibracji)
        self.angle_up = None
        self.angle_down = None
        self.ref_torso_lean = 0.0

        self.trening_log = []
        self.smoothed_landmarks = {}
        self.alpha = 0.5

    def speak(self, text, force=False):
        if not self.speech_lock.locked() or force:
            print(f"[TRENER MÓWI]: {text}")
            threading.Thread(target=self._speak_task, args=(text,), daemon=True).start()

    def _speak_task(self, text):
        with self.speech_lock:
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Rate = 2
                speaker.Speak(text)
                return
            except Exception:
                pass

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

    def check_pelvic_stability(self, left_hip, right_hip):
        """Analizuje asymetrię miednicy pod kątem opadania (Y) i skrętu (Z)"""
        # 1. Sprawdzenie opadania / asymetrii wysokości miednicy (oś Y)
        hip_drop = abs(left_hip.y - right_hip.y)
        
        # 2. Sprawdzenie rotacji / skrętu bioder w osi pionowej (oś Z)
        hip_twist = abs(left_hip.z - right_hip.z)
        
        if hip_drop > 0.06:   # Próg tolerancji dla różnicy wysokości bioder
            return False, "Krzywe biodra!"
        if hip_twist > 0.12:  # Próg tolerancji dla skrętu tułowia
            return False, "Nie skrecaj bioder!"
            
        return True, None

    def calculate_knee_valgus(self, hip, knee, ankle):
        """Mierzy odchylenie kolana od osi biodro-kostka w płaszczyźnie czołowej (oś X)"""
        line_vec = np.array(ankle) - np.array(hip)
        knee_vec = np.array(knee) - np.array(hip)
        
        line_len = np.linalg.norm(line_vec)
        if line_len == 0:
            return 0
        line_unit_vec = line_vec / line_len
        
        # Rzutowanie wektora kolana na oś biodro-kostka
        projection_len = np.dot(knee_vec, line_unit_vec)
        closest_point = np.array(hip) + projection_len * line_unit_vec
        
        # Lateralne odchylenie na ekranie (w pikselach)
        deviation = knee[0] - closest_point[0]
        return deviation

    def run(self):
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        with self.mp_pose.Pose(min_detection_confidence=0.6,
                               min_tracking_confidence=0.7,
                               model_complexity=1) as pose:

            self.speak("System gotowy. Podnies obie rece, aby rozpoczac.", force=True)

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

                h, w, _ = image.shape
                progress_val = 0
                ui_error_msg = None
                aktywna_noga = "BRAK"

                # Zmienne dla UI ładowania gestu
                gesture_progress = 0.0
                gesture_type = None

                if results.pose_landmarks:
                    try:
                        landmarks = results.pose_landmarks.landmark

                        # Pobieramy punkty do logiki przysiadu
                        left_ankle_lm = landmarks[self.mp_pose.PoseLandmark.LEFT_ANKLE.value]
                        right_ankle_lm = landmarks[self.mp_pose.PoseLandmark.RIGHT_ANKLE.value]

                        # Punkty do wykrywania gestów i stabilizacji
                        left_wrist = landmarks[self.mp_pose.PoseLandmark.LEFT_WRIST.value]
                        right_wrist = landmarks[self.mp_pose.PoseLandmark.RIGHT_WRIST.value]
                        left_eye = landmarks[self.mp_pose.PoseLandmark.LEFT_EYE.value]
                        right_eye = landmarks[self.mp_pose.PoseLandmark.RIGHT_EYE.value]
                        left_shoulder = landmarks[self.mp_pose.PoseLandmark.LEFT_SHOULDER.value]
                        right_shoulder = landmarks[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
                        left_hip_lm = landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value]
                        right_hip_lm = landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value]

                        # --- DETEKCJA GESTU: START (Ręce w górę) ---
                        if self.state == "CZEKA NA START":
                            if left_wrist.visibility > 0.5 and right_wrist.visibility > 0.5:
                                # Nadgarstki wyżej (y jest mniejsze) niż oczy
                                if left_wrist.y < left_eye.y and right_wrist.y < right_eye.y:
                                    if self.start_pose_timer == 0:
                                        self.start_pose_timer = time.time()

                                    elapsed = time.time() - self.start_pose_timer
                                    gesture_progress = min(elapsed / self.gesture_hold_time, 1.0)
                                    gesture_type = "START"

                                    if elapsed > self.gesture_hold_time:
                                        # --- DYNAMICZNA KALIBRACJA SYLWETKI ---
                                        is_right = right_ankle_lm.y > left_ankle_lm.y
                                        s_sub = landmarks[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value if is_right else self.mp_pose.PoseLandmark.LEFT_SHOULDER.value]
                                        h_sub = landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value if is_right else self.mp_pose.PoseLandmark.LEFT_HIP.value]
                                        k_sub = landmarks[self.mp_pose.PoseLandmark.RIGHT_KNEE.value if is_right else self.mp_pose.PoseLandmark.LEFT_KNEE.value]
                                        a_sub = landmarks[self.mp_pose.PoseLandmark.RIGHT_ANKLE.value if is_right else self.mp_pose.PoseLandmark.LEFT_ANKLE.value]
                                        
                                        p_shoulder = [s_sub.x * w, s_sub.y * h]
                                        p_hip = [h_sub.x * w, h_sub.y * h]
                                        p_knee = [k_sub.x * w, k_sub.y * h]
                                        p_ankle = [a_sub.x * w, a_sub.y * h]
                                        
                                        current_standing_knee = self.calculate_angle(p_hip, p_knee, p_ankle)
                                        self.ref_torso_lean = self.calculate_torso_lean(p_shoulder, p_hip)
                                        
                                        # Wyznaczenie zindywidualizowanych progów ruchu
                                        self.angle_up = int(current_standing_knee - 5)
                                        self.angle_down = int(current_standing_knee - 55)
                                        
                                        print(f"[SYSTEM CALIBRATION]: Kat gora={self.angle_up}, Kat dol={self.angle_down}, Ref. Plecy={self.ref_torso_lean:.1f}")
                                        
                                        self.state = "POWITANIE"
                                        self.start_time = time.time()
                                        self.start_pose_timer = 0
                                else:
                                    self.start_pose_timer = 0
                            else:
                                self.start_pose_timer = 0

                        # --- DETEKCJA GESTU: STOP (Ręce skrzyżowane na klatce) ---
                        elif self.state not in ["CZEKA NA START", "ZAKONCZONO"]:
                            if left_wrist.visibility > 0.5 and right_wrist.visibility > 0.5:
                                distance_wrists = abs(left_wrist.x - right_wrist.x)
                                # Nadgarstki blisko siebie, poniżej ramion, powyżej bioder
                                if distance_wrists < 0.15 and left_wrist.y > left_shoulder.y and left_wrist.y < left_hip_lm.y and right_wrist.y > right_shoulder.y:
                                    if self.stop_pose_timer == 0:
                                        self.stop_pose_timer = time.time()

                                    elapsed = time.time() - self.stop_pose_timer
                                    gesture_progress = min(elapsed / self.gesture_hold_time, 1.0)
                                    gesture_type = "STOP"

                                    if elapsed > self.gesture_hold_time:
                                        self.state = "ZAKONCZONO"
                                        self.speak(f"Koniec treningu. Wynik to {self.counter} powtorzen. Trzymaj sie!",
                                                   force=True)
                                        self.stop_pose_timer = time.time()  # Re-use do opóźnienia wyjścia
                                else:
                                    self.stop_pose_timer = 0

                        # ==========================================
                        # Właściwa logika przysiadu (aktywna tylko w trakcie treningu)
                        # ==========================================
                        if self.state not in ["CZEKA NA START", "ZAKONCZONO"]:
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

                            # MONITOROWANIE STABILNOŚCI MIEDNICY
                            pelvis_stable, pelvis_error = self.check_pelvic_stability(left_hip_lm, right_hip_lm)

                            # DETEKCJA KOŚLAWIENIA KOLANA (VALGUS)
                            knee_deviation = self.calculate_knee_valgus(hip, knee, ankle)
                            is_valgus = False
                            # Na zflipowanym obrazie środek ciała dla PRAWEJ nogi jest przy mniejszym X, dla LEWEJ przy większym X
                            if aktywna_noga == "PRAWA NOGA" and knee_deviation < -35:
                                is_valgus = True
                            elif aktywna_noga == "LEWA NOGA" and knee_deviation > 35:
                                is_valgus = True

                            progress_val = np.interp(knee_angle, [self.angle_down, self.angle_up], [100, 0])

                            if self.state not in ["POWITANIE", "GORA"]:
                                # Weryfikacja pochylenia w odniesieniu do pozycji bazowej
                                if abs(torso_lean_angle - self.ref_torso_lean) > 30.0:
                                    self.current_rep_valid = False
                                    self.errors_this_rep.add("Wyprostuj plecy!")
                                    ui_error_msg = "WYPROSTUJ PLECY!"
                                    
                                # Walidacja stabilności bioder
                                if not pelvis_stable:
                                    self.current_rep_valid = False
                                    self.errors_this_rep.add(pelvis_error)
                                    ui_error_msg = pelvis_error.upper()

                                # Walidacja koślawienia kolana
                                if is_valgus:
                                    self.current_rep_valid = False
                                    self.errors_this_rep.add("Kolano do zewnatrz!")
                                    ui_error_msg = "KOLANO UCIEKA DO SRODKA!"

                            # Fazy Ruchu
                            if self.state == "POWITANIE":
                                if time.time() - self.start_time > 3.0 and not self.is_greeting_done:
                                    self.speak("Czesc! Ustaw sie do przysiadu. Zaczynamy!", force=True)
                                    self.is_greeting_done = True
                                    self.state = "GORA"

                            elif self.state == "GORA":
                                if knee_angle < self.angle_up - 10:
                                    self.state = "W DOL"

                            elif self.state == "W DOL":
                                if knee_angle <= self.angle_down:
                                    self.state = "DOL"
                                elif knee_angle >= self.angle_up + 5:
                                    blad_msg = " ".join(self.errors_this_rep)
                                    self.speak(f"Niepelny! {blad_msg}", force=True)
                                    self.state = "GORA"
                                    self.current_rep_valid = True
                                    self.errors_this_rep.clear()

                            elif self.state == "DOL":
                                if knee_angle > self.angle_down + 10:
                                    self.state = "W GORE"

                            elif self.state == "W GORE":
                                if knee_angle >= self.angle_up:
                                    if self.current_rep_valid:
                                        self.counter += 1
                                        self.speak(f"Dobrze, {self.counter}", force=True)
                                        self.trening_log.append(
                                            f"Powtorzenie {self.counter} ({time.strftime('%H:%M:%S')})")
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

                # =======================================================
                # ============= RYSOWANIE INTERFEJSU (UI) ===============
                # =======================================================

                if results.pose_landmarks:
                    self.mp_drawing.draw_landmarks(
                        image, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS,
                        self.mp_drawing.DrawingSpec(color=(255, 255, 255), thickness=2, circle_radius=3),
                        self.mp_drawing.DrawingSpec(color=(0, 200, 255), thickness=2, circle_radius=2)
                    )

                overlay = image.copy()

                # --- WIDOK: EKRAN OCZEKIWANIA ---
                if self.state == "CZEKA NA START":
                    cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
                    cv2.addWeighted(overlay, 0.6, image, 0.4, 0, image)

                    text1 = "CYBER-TRENER"
                    text2 = "Podnies obie rece, aby rozpoczac"

                    cv2.putText(image, text1, (w // 2 - 200, h // 2 - 50), cv2.FONT_HERSHEY_DUPLEX, 1.8, (255, 200, 0),
                                3, cv2.LINE_AA)
                    cv2.putText(image, text2, (w // 2 - 320, h // 2 + 20), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                                (255, 255, 255), 2, cv2.LINE_AA)

                    # Pasek postępu gestu startu
                    if gesture_progress > 0:
                        box_w = 400
                        box_x = w // 2 - box_w // 2
                        box_y = h // 2 + 80
                        cv2.rectangle(image, (box_x, box_y), (box_x + box_w, box_y + 20), (50, 50, 50), -1)
                        cv2.rectangle(image, (box_x, box_y), (box_x + int(box_w * gesture_progress), box_y + 20),
                                      (0, 255, 0), -1)
                        cv2.putText(image, "Inicjalizacja...", (box_x, box_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                    (0, 255, 0), 1, cv2.LINE_AA)

                # --- WIDOK: ZAKOŃCZENIE ---
                elif self.state == "ZAKONCZONO":
                    cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
                    cv2.addWeighted(overlay, 0.8, image, 0.2, 0, image)

                    cv2.putText(image, "TRENING ZAKONCZONY", (w // 2 - 350, h // 2 - 50), cv2.FONT_HERSHEY_DUPLEX, 2.0,
                                (0, 255, 0), 4, cv2.LINE_AA)
                    cv2.putText(image, f"Zaliczono: {self.counter} powtorzen", (w // 2 - 200, h // 2 + 40),
                                cv2.FONT_HERSHEY_DUPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)

                    # Wyjście z programu po 4 sekundach od pokazania ekranu końcowego
                    if time.time() - self.stop_pose_timer > 4.0:
                        break

                # --- WIDOK: TRENING ---
                else:
                    cv2.rectangle(overlay, (0, 0), (w, 100), (25, 25, 30), -1)
                    cv2.rectangle(overlay, (0, 100), (w, 103), (100, 100, 100), -1)

                    bar_w = 40
                    bar_h = int(h * 0.6)
                    bar_x = w - 70
                    bar_y_start = int(h * 0.25)
                    bar_y_end = bar_y_start + bar_h
                    cv2.rectangle(overlay, (bar_x, bar_y_start), (bar_x + bar_w, bar_y_end), (50, 50, 50), -1)

                    if ui_error_msg:
                        cv2.rectangle(overlay, (0, h - 120), (w, h), (0, 0, 200), -1)

                    cv2.addWeighted(overlay, 0.85, image, 0.15, 0, image)

                    # Pasek postępu dla gestu STOP (na żywo, jeśli w trakcie treningu skrzyżujesz ręce)
                    if gesture_progress > 0 and gesture_type == "STOP":
                        cv2.putText(image, "ZAKONCZYC?", (w // 2 - 80, h // 2 - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                    (0, 0, 255), 2, cv2.LINE_AA)
                        box_w = 200
                        box_x = w // 2 - box_w // 2
                        box_y = h // 2
                        cv2.rectangle(image, (box_x, box_y), (box_x + box_w, box_y + 15), (50, 50, 50), -1)
                        cv2.rectangle(image, (box_x, box_y), (box_x + int(box_w * gesture_progress), box_y + 15),
                                      (0, 0, 255), -1)

                    # Statystyki z Dashboardu
                    cv2.putText(image, 'POWTORZENIA', (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 2,
                                cv2.LINE_AA)
                    rep_color = (100, 255, 100) if self.current_rep_valid else (50, 50, 255)
                    cv2.putText(image, f'{self.counter:02d}', (30, 85), cv2.FONT_HERSHEY_DUPLEX, 1.5, rep_color, 3,
                                cv2.LINE_AA)

                    cv2.putText(image, 'FAZA RUCHU', (250, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 2,
                                cv2.LINE_AA)
                    cv2.putText(image, self.state, (250, 85), cv2.FONT_HERSHEY_DUPLEX, 1.3, (255, 200, 0), 2,
                                cv2.LINE_AA)

                    cv2.putText(image, 'CYBER-TRENER PRO', (w - 300, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (255, 255, 255), 2, cv2.LINE_AA)
                    leg_color = (100, 255, 100) if aktywna_noga != "BRAK" else (50, 50, 255)
                    cv2.putText(image, f'CEL: {aktywna_noga}', (w - 300, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6, leg_color,
                                2, cv2.LINE_AA)

                    # Dynamiczny pasek
                    fill_height = int(bar_h * (progress_val / 100.0))
                    fill_height = max(0, min(fill_height, bar_h))
                    bar_color = (50, 50, 255) if not self.current_rep_valid else (100, 255, 100)

                    if fill_height > 0:
                        cv2.rectangle(image, (bar_x, bar_y_end - fill_height), (bar_x + bar_w, bar_y_end), bar_color,
                                      -1)

                    cv2.rectangle(image, (bar_x, bar_y_start), (bar_x + bar_w, bar_y_end), (200, 200, 200), 2,
                                  cv2.LINE_AA)
                    cv2.putText(image, f"{int(progress_val)}%", (bar_x - 15, bar_y_end + 35), cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (255, 255, 255), 2, cv2.LINE_AA)

                    # Baner błędu
                    if ui_error_msg:
                        text_size = cv2.getTextSize(ui_error_msg, cv2.FONT_HERSHEY_DUPLEX, 1.8, 4)[0]
                        text_x = (w - text_size[0]) // 2
                        text_y = h - 40
                        cv2.putText(image, ui_error_msg, (text_x + 2, text_y + 2), cv2.FONT_HERSHEY_DUPLEX, 1.8,
                                    (0, 0, 0), 4, cv2.LINE_AA)
                        cv2.putText(image, ui_error_msg, (text_x, text_y), cv2.FONT_HERSHEY_DUPLEX, 1.8,
                                    (255, 255, 255), 4, cv2.LINE_AA)

                cv2.imshow('Cyber-Trener: Przysiad Bulgarski', image)

                # Wcisniecie Q nadal dziala jako opcja awaryjna
                if cv2.waitKey(10) & 0xFF == ord('q'):
                    break

        # Zapisz logi na koniec
        if self.counter > 0:
            with open("historia_treningow.txt", "a") as f:
                f.write(f"\n--- Trening z dnia {time.strftime('%Y-%m-%d %H:%M')} ---\n")
                for wpis in self.trening_log:
                    f.write(wpis + "\n")
                f.write(f"Suma powtorzen: {self.counter}\n")

        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    trainer = BulgarianSquatTrainer()
    trainer.run()
