fn main() {
    let n = 10_000_000;
    let mut sum = 0u64;
    for i in 0..n {
        sum = sum.wrapping_add(i);
        sum = sum.wrapping_mul(2);
        sum = sum.wrapping_sub(i / 2);
    }
    println!("Result: {}", sum);
}
