# ТОЧНАЯ (целочисленная, без float) проверка числовых характеристик.
#
# X равномерна на {0,1,2}, P = 1/3.  mu = 1,  E[X^2] = 5/3,  sigma^2 = 2/3.
# n = 2 (i.i.d.): 9 равновероятных пар (X1,X2), Xbar = (X1+X2)/2.
# Каждое тело ВЫЧИСЛЯЕТ величину суммированием по распределению;
# контракт утверждает равенство двух путей. Разность обязана быть 0.

# @kern:ensures result == 0
# E[Xbar] = mu.  Масштаб 18 = 9 пар * 2 (знаменатель Xbar).
def id_mean_n2() -> int:
    s = (0+1+2) + (1+2+3) + (2+3+4)   # sum_{i,j}(i+j) = 18
    direct = s                         # E[Xbar]*18 = s/(9*2)*18 = s
    formula = 18                       # mu*18
    return direct - formula

# @kern:ensures result == 0
# Var(Xbar) = sigma^2/n.  Масштаб 36 = 9 пар * 4 (квадрат знаменателя).
def id_var_mean_n2() -> int:
    s2 = (0+1+4) + (1+4+9) + (4+9+16)  # sum_{i,j}(i+j)^2 = 48
    direct = s2 - 36                   # E[Xbar^2]*36 - (E[Xbar])^2*36
    formula = (2 * 36) // 3 // 2       # sigma^2*36/n = 24/2 = 12
    return direct - formula

# @kern:ensures result == 0
# Var(X1+X2) = 2*sigma^2 (независимость -> ковариация нулевая).  Масштаб 9.
def id_var_sum_n2() -> int:
    s2 = (0+1+4) + (1+4+9) + (4+9+16)  # 48
    direct = s2 - 36                   # (E[(X1+X2)^2] - (E[X1+X2])^2) * 9
    formula = 2 * ((2 * 9) // 3)       # 2*sigma^2*9 = 12
    return direct - formula

# @kern:ensures result == 0
# Cov(X,X) = Var(X). Слева — определение E[(X-mu)^2], справа — E[X^2]-mu^2.
def id_cov_xx() -> int:
    direct = (0-1)*(0-1) + (1-1)*(1-1) + (2-1)*(2-1)   # E[(X-mu)^2]*3 = 2
    formula = 5 - 3                                     # (E[X^2]-mu^2)*3
    return direct - formula

# @kern:ensures result == 0
# Var(aX+b) = a^2*Var(X) при a=2, b=1.  Y = 2X+1 in {1,3,5}.
def id_var_affine() -> int:
    direct = (1+9+25) - 27             # Var(Y)*3 = 35 - 27 = 8
    formula = 2 * 2 * (5 - 3)          # a^2 * Var(X)*3 = 8
    return direct - formula

# @kern:ensures result == 0
# SD(Xbar) = sigma/sqrt(n) — ТОЧНО только когда sigma^2/n — полный квадрат.
# X равномерна на {0,2}: sigma^2 = 1, n = 4 -> Var(Xbar) = 1/4, SD = 1/2.
def id_sd_mean_n4() -> int:
    direct = 1                         # SD(Xbar)*2 = 1
    formula = 1 * 2 // 2               # sigma*2/sqrt(4) = 1
    return direct - formula

# @kern:ensures result == 0
# ОБХОД для Python: квадраты раскрыты ВРУЧНУЮ -> выражение линейно и доказуемо
# в Int-теории (в Python BV был бы НЕЗВУКОВЫМ: целые неограниченны).
def id_cov_xx_expanded() -> int:
    direct = 1 + 0 + 1                 # (0-1)^2 + (1-1)^2 + (2-1)^2, раскрыто
    formula = 5 - 3
    return direct - formula

# @kern:ensures result == 0
# То же для Var(aX+b) = a^2*Var(X): a^2 раскрыто как 4.
def id_var_affine_expanded() -> int:
    direct = (1+9+25) - 27             # Var(Y)*3, Y=2X+1
    formula = 4 * (5 - 3)              # 4 * Var(X)*3  (4 = a^2, раскрыто)
    return direct - formula
