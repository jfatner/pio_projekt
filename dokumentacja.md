# Dokumentacja Projektowa – Cyber-Trener (Wersja PRO)

## 1. Specyfikacja Wymagań i Reguł Biomechanicznych

### Cel systemu
Aplikacja służy do automatycznego monitorowania, oceny i zliczania powtórzeń podczas wykonywania przysiadów bułgarskich za pomocą analizy obrazu z kamery w czasie rzeczywistym. System ma na celu eliminowanie najczęstszych błędów technicznych zagrażających zdrowiu ćwiczącego.

### Bezdotykowy system sterowania (Gesty)
* **Start systemu:** Uniesienie obu rąk (nadgarstki powyżej linii oczu) przez minimum 2 sekundy aktywuje tryb kalibracji i rozpoczyna trening.
* **Stop systemu:** Skrzyżowanie rąk na klatce piersiowej (nadgarstki blisko siebie, poniżej linii ramion i powyżej bioder) przez 2 sekundy kończy trening i zapisuje historię sesji.

### Algorytmy walidacji postawy i progi tolerancji
Wersja PRO wprowadza dynamiczną kalibrację anatomiczną oraz zaawansowaną kontrolę stabilizacji wielopłaszczyznowej:

1. **Dynamiczna Kalibracja Zakresu Ruchu:** Podczas startu system mierzy naturalny kąt stania użytkownika (K_stand). Na tej podstawie wyliczane są indywidualne progi:
   * **Faza górna (GÓRA):** Kąt w kolanie >= K_stand - 5°
   * **Faza dolna (DÓŁ):** Kąt w kolanie <= K_stand - 55° (głęboki, bezpieczny przysiad).
2. **Kontrola Pochylenia Tułowia:** System zapamiętuje wyjściowy kąt pleców podczas stania. Jeśli w trakcie przysiadu odchylenie tułowia od pozycji referencyjnej przekroczy 30°, aktywowany jest błąd *"Wyprostuj plecy!"*.
3. **Stabilizacja Miednicy (Pelvic Stability):** Aplikacja śledzi pozycję bioder w przestrzeni 3D:
   * **Asymetria wysokości (Oś Y):** Różnica pozycji bioder > 0.06 generuje błąd *"Krzywe biodra!"*.
   * **Rotacja/Skręt miednicy (Oś Z):** Różnica głębokości bioder > 0.12 generuje błąd *"Nie skręcaj bioder!"*.
4. **Wykrywanie Koślawienia Kolana (Knee Valgus):**
   Mierzone jest lateralne odchylenie kolana od osi biodro-kostka w płaszczyźnie czołowej (Oś X). Przekroczenie progu 35 pikseli do wewnątrz generuje alert *"Kolano ucieka do środka!"*.

### Odnośniki do źródeł wiedzy biomechanicznej
Logika biznesowa systemu została oparta na poniższych publikacjach naukowych:
* *Biomechanics of the Single-Leg Squat and Bulgarian Split Squat:* [National Strength and Conditioning Association (NSCA)](https://www.nsca.com)
* *Knee valgus and pelvic drop in unilateral lower extremity exercises:* [Journal of Sports Science & Medicine](https://www.jssm.org)

---

## 2. Diagram Przypadków Użycia (Use Case Diagram)

```mermaid
graph TD
    Uzytkownik((Użytkownik)) --- UC1(Inicjalizacja i Start treningu gestem)
    Uzytkownik((Użytkownik)) --- UC2(Wykonywanie przysiadów)
    Uzytkownik((Użytkownik)) --- UC3(Zakończenie treningu gestem)
    
    UC1 --> In0(<< include >> Dynamiczna kalibracja sylwetki)
    UC2 --> In1(<< include >> Ocena poprawności postawy)
    UC2 --> In2(<< include >> Zliczanie powtórzeń)
    
    In1 --> In1a(Walidacja pochylenia tułowia)
    In1 --> In1b(Kontrola stabilności miednicy)
    In1 --> In1c(Wykrywanie koślawienia kolan)
    
    UC4(Otrzymywanie wskazówek głosowych) .->|<< extend >>| UC2
    UC4 --- TTS((Silnik TTS))
    
    UC3 --> In3(<< include >> Zapis historii do pliku)


classDiagram
    class BulgarianSquatTrainer {
        -pose_detector: PoseDetector
        -state_machine: SquatStateMachine
        -validator: BiomechanicalValidator
        -logger: TrainingLogger
        -ui_manager: UIManager
        -speech_synthesizer: SpeechSynthesizer
        +run() void
    }

    class PoseDetector {
        -mp_pose: mp.solutions.pose
        -smoothed_landmarks: dict
        -alpha: float
        +process_frame(frame) dict
        +smooth_landmark(name, current_pt, side) list
        +calculate_angle(a, b, c) float
    }

    class BiomechanicalValidator {
        +calculate_torso_lean(shoulder, hip) float
        +check_pelvic_stability(left_hip, right_hip) tuple
        +calculate_knee_valgus(hip, knee, ankle) float
    }

    class SquatStateMachine {
        +state: String
        +counter: int
        +current_rep_valid: bool
        +errors_this_rep: set
        +angle_up: int
        +angle_down: int
        +ref_torso_lean: float
        +calibrate_thresholds(standing_knee, standing_torso) void
        +update_state(knee_angle, current_torso, pelvis_stable, is_valgus) void
    }

    class SpeechSynthesizer {
        -speech_lock: Threading.Lock
        +speak(text, force) void
        -_speak_task(text) void
    }

    class TrainingLogger {
        -file_path: String
        +save_logs(counter, log_list) void
    }

    class UIManager {
        +draw_skeleton(image, landmarks) void
        +draw_dashboard(image, state, counter, progress) void
        +draw_error_banner(image, message) void
    }

    BulgarianSquatTrainer *-- PoseDetector
    BulgarianSquatTrainer *-- BiomechanicalValidator
    BulgarianSquatTrainer *-- SquatStateMachine
    BulgarianSquatTrainer *-- SpeechSynthesizer
    BulgarianSquatTrainer *-- TrainingLogger
    BulgarianSquatTrainer *-- UIManager


graph TD
    subgraph Stacja_Robocza_PC [Komputer Użytkownika PC/Laptop]
        subgraph Srodowisko_Python [Środowisko Python 3.x]
            Artifact1[«artifact» cyber_trener.py]
            Artifact2[«artifact» historia_treningow.txt]
        end
        Systemowe_API [System OS API - Windows SAPI / Linux espeak]
    end

    Kamera [«device» Kamera Internetowa] -->|Przechwytywanie klatek OpenCV| Artifact1
    Artifact1 -->|Żądanie syntezy mowy| Systemowe_API
    Systemowe_API -->|Wyjście audio| Glosniki [«device» Głośniki/Słuchawki]
    Artifact1 ..>|Zapis tekstowy File I/O| Artifact2
