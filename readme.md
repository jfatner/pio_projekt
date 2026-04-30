# CYBER-TRENER: INTELIGENTNY ASYSTENT PRZYSIADU BUŁGARSKIEGO

Projekt realizowany w ramach przedmiotu **Komunikacja człowiek-komputer 2026**.

## Zespół Projektowy 
* ** Janusz Fątner **
* ** Piotr Michałkiewicz **
* ** Jan Radziszowski **

## Opis projektu

**Cyber-Trener** to stacjonarny system wspierający trening fizyczny, skupiający się na jednym z najbardziej wymagających technicznie ćwiczeń – **przysiadzie bułgarskim (Bulgarian Split Squat)**. System wykorzystuje kamerę laptopa oraz algorytmy sztucznej inteligencji do analizy pozy ćwiczącego w czasie rzeczywistym, informując o błędach za pomocą komunikatów głosowych.

## Biblioteki użyte w projekcie 

* **cv2 (OpenCV)** – Przechwytywanie obrazu z kamery oraz renderowanie interfejsu (HUD z licznikiem i komunikatami) bezpośrednio na wideo.  

* **mediapipe** – Zaawansowana detekcja sylwetki i śledzenie punktów kluczowych ciała (stawów) w czasie rzeczywistym.  

* **numpy** – Optymalizacja obliczeń matematycznych i trygonometria niezbędna do mierzenia kątów w stawach.  

* **pyttsx3** – Silnik Text-to-Speech (TTS) działający offline, generujący komunikaty głosowe trenera.  

* **threading** – Asynchroniczna obsługa mowy w tle (jako daemon), dzięki czemu odtwarzanie dźwięku nie zacina podglądu z kamery.  

* **time** – Zarządzanie interwałami (cooldown) komunikatów, zapobiegające "spamowaniu" uwagami przez trenera.  

* **queue** – Zapewnienie płynnej kolejki dla powiadomień głosowych, eliminujące nakładanie się dźwięków.

* **math** – Obliczanie relatywnych proporcji ciała, uniezależniające dokładność trenera od odległości ćwiczącego od kamery.
