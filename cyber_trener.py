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

        self.state = "KALIBRACJA"
        self.counter = 0
        self.current_rep_valid = True
        self.last_feedback_time = 0
        self.feedback_cooldown = 2.0
        self.start_time = time.time()
        self.angle_up = 160
        self.angle_down = 95

        self.active_side = None
        self.trening_log = []

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
        a, b, c = np.array(a), np.array(b), np.array(c)
        radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
        angle = np.abs(radians * 180.0 / np.pi)
        if angle > 180.0:
            angle = 360 - angle
        return angle

    @staticmethod
    def calculate_distance(p1, p2):
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def calculate_torso_lean(self, shoulder, hip):
        vertical_pt = [hip[0], hip[1] - 1.0]
        return self.calculate_angle(shoulder, hip, vertical_pt)

    def run(self):
        cap = cv2.VideoCapture(0)
        with self.mp_pose.Pose(min_detection_confidence=0.7, min_tracking_confidence=0.7) as pose:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image.flags.writeable = False
                results = pose.process(image)
                image.flags.writeable = True
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

                h, w, _ = image.shape
                progress_val = 0
                current_error_msg = None

                if results.pose_landmarks:
                    landmarks = results.pose_landmarks.landmark

                    try:
                        # 1. KALIBRACJA SYLWETKI
                        if self.state == "KALIBRACJA":
                            # Sprawdzamy czy widać kluczowe punkty
                            required_joints = [
                                self.mp_pose.PoseLandmark.LEFT_ANKLE, self.mp_pose.PoseLandmark.RIGHT_ANKLE,
                                self.mp_pose.PoseLandmark.LEFT_KNEE, self.mp_pose.PoseLandmark.RIGHT_KNEE,
                                self.mp_pose.PoseLandmark.LEFT_HIP, self.mp_pose.PoseLandmark.RIGHT_HIP
                            ]
                            is_visible = all(landmarks[j.value].visibility > 0.6 for j in required_joints)

                            if is_visible:
                                self.speak("Sylwetka wykryta. Rozpocznij ruch, aby wybrać nogę.")
                                self.state = "POWITANIE"
                            else:
                                current_error_msg = "Ustaw się tak, by było widać całe nogi"

                        # 2. AUTOMATYCZNA DETEKCJA NOGI
                        if self.active_side is None:
                            l_knee_y = landmarks[self.mp_pose.PoseLandmark.LEFT_KNEE.value].y
                            r_knee_y = landmarks[self.mp_pose.PoseLandmark.RIGHT_KNEE.value].y
                            if abs(l_knee_y - r_knee_y) > 0.05:  # Jeśli jedna noga jest wyraźnie niżej
                                self.active_side = "LEFT" if l_knee_y > r_knee_y else "RIGHT"
                                self.speak(f"Wykryto nogę {'lewą' if self.active_side == 'LEFT' else 'prawą'}")

                        side = self.active_side if self.active_side else "LEFT"

                        # Pobieranie punktów dynamicznie
                        shldr = [landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_SHOULDER").value].x,
                                 landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_SHOULDER").value].y]
                        hip = [landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_HIP").value].x,
                               landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_HIP").value].y]
                        knee = [landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_KNEE").value].x,
                                landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_KNEE").value].y]
                        ankle = [landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_ANKLE").value].x,
                                 landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_ANKLE").value].y]
                        toe = [landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_FOOT_INDEX").value].x,
                               landmarks[getattr(self.mp_pose.PoseLandmark, f"{side}_FOOT_INDEX").value].y]

                        # Obliczenia
                        knee_angle = self.calculate_angle(hip, knee, ankle)
                        torso_lean_angle = self.calculate_torso_lean(shldr, hip)

                        # Monitorowanie miednicy (różnica wysokości bioder)
                        hip_l_y = landmarks[self.mp_pose.PoseLandmark.LEFT_HIP.value].y
                        hip_r_y = landmarks[self.mp_pose.PoseLandmark.RIGHT_HIP.value].y
                        hip_imbalance = abs(hip_l_y - hip_r_y)

                        # Koślawienie kolana (odchylenie kolana od linii biodro-kostka w osi X)
                        knee_valgus = abs(knee[0] - (hip[0] + ankle[0]) / 2)

                        ref_length = self.calculate_distance(shldr, hip)
                        if ref_length == 0: ref_length = 0.01
                        distance_knee_toe_rel = abs(knee[0] - toe[0]) / ref_length

                        progress_val = np.interp(knee_angle, [self.angle_down, self.angle_up], [100, 0])

                        # LOGIKA BŁĘDÓW
                        if self.state not in ["POWITANIE", "KALIBRACJA"]:
                            if torso_lean_angle > 45.0:
                                current_error_msg = "Wyprostuj plecy!"
                            elif hip_imbalance > 0.08:
                                current_error_msg = "Trzymaj biodra równo!"
                            elif knee_valgus > 0.05:
                                current_error_msg = "Kolano ucieka do środka!"
                            elif self.state in ["W_DOL", "DOL"] and distance_knee_toe_rel > 0.25:
                                current_error_msg = "Wydłuż krok!"

                            if current_error_msg:
                                self.current_rep_valid = False
                                if time.time() - self.last_feedback_time > self.feedback_cooldown:
                                    self.speak(current_error_msg)
                                    self.last_feedback_time = time.time()

                        # MASZYNA STANÓW
                        if self.state == "POWITANIE":
                            if time.time() - self.start_time > 2.0:
                                self.speak("Zaczynamy trening!", force=True)
                                self.state = "GORA"

                        elif self.state == "GORA":
                            if knee_angle < self.angle_up - 10:
                                self.state = "W_DOL"

                        elif self.state == "W_DOL":
                            if knee_angle <= self.angle_down:
                                self.state = "DOL"
                                if self.current_rep_valid: self.speak("Góra!")

                        elif self.state == "DOL":
                            if knee_angle > self.angle_down + 10:
                                self.state = "W_GORE"

                        elif self.state == "W_GORE":
                            if knee_angle >= self.angle_up:
                                if self.current_rep_valid:
                                    self.counter += 1
                                    self.speak(str(self.counter))
                                    self.trening_log.append(
                                        f"Powtórzenie {self.counter} ({side}) - OK - {time.strftime('%H:%M:%S')}")
                                else:
                                    self.speak("Powtórzenie spalone")
                                self.current_rep_valid = True
                                self.state = "GORA"

                    except Exception as e:
                        pass

                    self.mp_drawing.draw_landmarks(image, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)

                # UI
                cv2.rectangle(image, (0, 0), (320, 85), (245, 117, 16), -1)
                cv2.putText(image, f'POWT: {self.counter}', (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                cv2.putText(image, f'STAN: {self.state}', (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                cv2.putText(image, f'NOGA: {self.active_side if self.active_side else "SZUKAM..."}', (160, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

                if current_error_msg:
                    cv2.rectangle(image, (0, h - 40), (w, h), (0, 0, 255), -1)
                    cv2.putText(image, current_error_msg, (w // 2 - 150, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                (255, 255, 255), 2)

                # Pasek postępu
                bar_x = w - 50
                cv2.rectangle(image, (bar_x, 100), (bar_x + 30, h - 100), (50, 50, 50), -1)
                fill_h = int(np.interp(progress_val, [0, 100], [0, h - 200]))
                col = (0, 255, 0) if self.current_rep_valid else (0, 0, 255)
                cv2.rectangle(image, (bar_x, h - 100 - fill_h), (bar_x + 30, h - 100), col, -1)

                cv2.imshow('Cyber Trener Pro', image)
                if cv2.waitKey(10) & 0xFF == ord('q'):
                    break

        if self.counter > 0:
            with open("historia_treningow.txt", "a", encoding='utf-8') as f:
                f.write(f"\n--- Sesja: {time.strftime('%Y-%m-%d %H:%M')} ---\n")
                for wpis in self.trening_log:
                    f.write(wpis + "\n")
                f.write(f"Łącznie: {self.counter} powtórzeń.\n")

        self.tts_queue.put(None)
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    trainer = BulgarianSquatTrainer()
    trainer.run()
