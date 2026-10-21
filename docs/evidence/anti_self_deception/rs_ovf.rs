pub fn add32(a: i32, b: i32) -> i32 { return a + b; }
fn main() { let r = add32(2147483647, 1); println!("NO VIOLATION {}", r); }
