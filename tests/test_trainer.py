from cyber_trener import BulgarianSquatTrainer

# Klasa pomocnicza udająca punkt z MediaPipe
class MockLandmark:
    def __init__(self, y, z):
        self.y = y
        self.z = z

def test_calculate_angle_90_degrees():
    a = [0, 1]
    b = [0, 0]
    c = [1, 0]
    wynik = BulgarianSquatTrainer.calculate_angle(a, b, c)
    assert wynik == 90.0

def test_pelvic_stability_detects_hip_drop():
    left_hip = MockLandmark(y=0.5, z=0.0)
    right_hip = MockLandmark(y=0.61, z=0.0)
    
    stable, error_msg = BulgarianSquatTrainer.check_pelvic_stability(None, left_hip, right_hip)
    
    assert stable is False
    assert error_msg == "Krzywe biodra!"
