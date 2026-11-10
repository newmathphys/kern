# Двусторонний контроль --gen-tests: ЖИВАЯ ветвь (нельзя объявлять недостижимой)
def live_branch(items: list[int], item: int) -> int:
    index = 2
    if index < len(items) and items[index] == item:
        return index
    return -1
