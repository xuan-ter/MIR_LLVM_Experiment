use std::hint::black_box;
use std::time::Instant;

fn xorshift32(mut x: u32) -> u32 {
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    x
}

fn make_data(len: usize, seed: u32) -> Vec<u32> {
    let mut v = Vec::with_capacity(len);
    let mut x = seed;
    for _ in 0..len {
        x = xorshift32(x);
        v.push(x);
    }
    v
}

#[export_name = "loop_easy"]
#[inline(never)]
pub fn loop_easy(data: &[u32], iters: u32, seed: u32) -> u64 {
    let mut sum: u64 = 0;
    for _ in 0..iters {
        for &x in data {
            let factor = seed.wrapping_mul(7).wrapping_add(3);
            sum = sum.wrapping_add((x.wrapping_mul(factor)) as u64);
        }
    }
    black_box(sum)
}

#[inline(always)]
pub fn compute_factor_mir(seed: u32) -> u32 {
    let a = seed ^ 13;
    let b = a.wrapping_mul(7);
    let c = b.wrapping_add(3);
    let d = c.rotate_left(5) ^ (c >> 3);
    let e = seed.wrapping_add(1);
    let f = e.wrapping_add(2);
    let g = if (seed & 1) == 0 { f } else { f };
    d.wrapping_add(g)
}

#[export_name = "loop_mir_dependent"]
#[inline(never)]
pub fn loop_mir_dependent(data: &[u32], iters: u32, seed: u32) -> u64 {
    let mut sum: u64 = 0;
    for _ in 0..iters {
        for &x in data {
            let factor = compute_factor_mir(seed);
            sum = sum.wrapping_add((x.wrapping_mul(factor)) as u64);
        }
    }
    black_box(sum)
}

fn parse_arg_u64(flag: &str, default: u64) -> u64 {
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        if a == flag {
            if let Some(v) = args.next() {
                return v.parse::<u64>().unwrap_or(default);
            }
        }
    }
    default
}

fn parse_arg_string(flag: &str, default: &str) -> String {
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        if a == flag {
            if let Some(v) = args.next() {
                return v;
            }
        }
    }
    default.to_string()
}

fn main() {
    let mode = parse_arg_string("--mode", "mir-dependent");
    let len = parse_arg_u64("--len", 1 << 16) as usize;
    let iters = parse_arg_u64("--iters", 8000) as u32;
    let seed = parse_arg_u64("--seed", 1) as u32;

    let seed = black_box(seed);
    let data = make_data(len, seed);
    let data = black_box(data);

    let start = Instant::now();
    let sum = match mode.as_str() {
        "easy" => loop_easy(&data, iters, seed),
        _ => loop_mir_dependent(&data, iters, seed),
    };
    let elapsed = start.elapsed().as_secs_f64();

    println!("Mode: {}", mode);
    println!("Len: {}", len);
    println!("Iters: {}", iters);
    println!("Sum: {}", sum);
    println!("Total Time: {:.6} s", elapsed);
    println!("Throughput: {:.2} iters/s", (len as f64 * iters as f64) / elapsed);
}
