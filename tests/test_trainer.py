from cyber_trener import BulgarianSquatTrainer

def test_calculate_angle_90_degrees():
    a = [0, 1]
    b = [0, 0]
    c = [1, 0]
    wynik = BulgarianSquatTrainer.calculate_angle(a, b, c)
    assert wynik == 90.0
