pub fn kernel_easy(a: &[u32], b: &[u32], rounds: u32, alpha: u32, beta: u32, c: u32) -> u64 {
    let mut sum: u64 = 0;
    for _ in 0..rounds {
        let s: u32 = a
            .iter()
            .zip(b.iter())
            .map(|(&x, &y)| {
                let t0 = x.wrapping_mul(alpha);
                let t1 = y.wrapping_mul(beta);
                t0.wrapping_add(t1).wrapping_add(c)
            })
            .sum();
        sum = sum.wrapping_add(s as u64);
    }
    sum
}

fn step_add_pair(p: (u32, u32), ax: u32, ay: u32) -> (u32, u32) {
    (p.0.wrapping_add(ax), p.1.wrapping_add(ay))
}

fn step_sub_pair(p: (u32, u32), sx: u32, sy: u32) -> (u32, u32) {
    (p.0.wrapping_sub(sx), p.1.wrapping_sub(sy))
}

fn step_pack_unpack(p: (u32, u32)) -> (u32, u32) {
    let (x, y) = p;
    (x, y)
}

fn step_xor_zero(p: (u32, u32)) -> (u32, u32) {
    (p.0 ^ 0, p.1 ^ 0)
}

pub fn kernel_mir_dependent(
    a: &[u32],
    b: &[u32],
    rounds: u32,
    alpha: u32,
    beta: u32,
    c: u32,
) -> u64 {
    let mut sum: u64 = 0;
    for _ in 0..rounds {
        let s: u32 = a
            .iter()
            .zip(b.iter())
            .map(|(&x, &y)| (x, y))
            .map(|p| step_add_pair(p, 1, 2))
            .map(|p| step_sub_pair(p, 1, 2))
            .map(step_pack_unpack)
            .map(step_xor_zero)
            .map(|(x, y)| {
                let t0 = x.wrapping_mul(alpha);
                let t1 = y.wrapping_mul(beta);
                t0.wrapping_add(t1).wrapping_add(c).wrapping_add(0) ^ 0
            })
            .fold(0u32, |acc, v| acc.wrapping_add(v));
        sum = sum.wrapping_add(s as u64);
    }
    sum
}
