# РЕАЛЬНЫЙ алгоритм с ВЛОЖЕННЫМ циклом (TheAlgorithms/Python, segmented_sieve.py)
# списки переданы параметрами (их создание — вне модели, но это НЕ логика цикла)
# @kern:requires n >= 4
# @kern:invariant 2 <= start and start <= end + 1
# @kern:decreases end - start
def sieve_first_block(temp: list, in_prime: list, n: int) -> int:
    start = 2
    end = n // 2
    while start <= end:
        if temp[start]:
            in_prime.append(start)
            for i in range(start * start, end + 1, start):
                temp[i] = False
        start += 1
    return len(in_prime)
