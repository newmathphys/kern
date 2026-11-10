# Двусторонний контроль --heal: путь деления на ноль ЕСТЬ -> патч с raise
# @kern:requires volume != 0
def rate(moles: int, volume: int) -> int:
    return moles // volume
