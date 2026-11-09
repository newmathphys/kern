from bank import fee

def test_fee():
    assert fee(1000) == 10
