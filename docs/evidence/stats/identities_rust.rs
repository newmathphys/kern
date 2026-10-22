// Cov(X,X) = Var(X): слева E[(X-mu)^2], справа E[X^2]-mu^2.
// @kern:ensures result == 0
fn id_cov_xx() -> i32 {
    return ((0-1)*(0-1) + (1-1)*(1-1) + (2-1)*(2-1)) - (5 - 3);
}

// Var(aX+b) = a^2*Var(X), a=2, b=1.
// @kern:ensures result == 0
fn id_var_affine() -> i32 {
    return ((1+9+25) - 27) - (2*2*(5-3));
}
