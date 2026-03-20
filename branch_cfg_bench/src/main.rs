use std::hint::black_box;
use std::time::Instant;

fn xorshift32(mut x: u32) -> u32 {
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    x
}

fn make_data(n: usize, seed: u32) -> Vec<u32> {
    let mut v = Vec::with_capacity(n);
    let mut x = seed;
    for _ in 0..n {
        x = xorshift32(x);
        v.push(x);
    }
    v
}

#[inline(never)]
fn postprocess(mut t: u32) -> u32 {
    t = t.wrapping_mul(1664525).wrapping_add(1013904223);
    t ^= t.rotate_left(7);
    t = t.wrapping_mul(2246822519);
    t ^ (t >> 16)
}

#[export_name = "workload_a"]
#[inline(never)]
pub fn workload_a(data: &[u32], iters: u32) -> u64 {
    let mut sum: u64 = 0;
    for _ in 0..iters {
        for &x in data {
            let t: u32;
            if (x & 1) == 0 {
                t = x.wrapping_add(3);
            } else if (x & 2) == 0 {
                t = x.wrapping_add(3);
            } else if (x & 4) == 0 {
                t = x.wrapping_add(3);
            } else {
                t = x.wrapping_add(7);
            }
            sum = sum.wrapping_add(postprocess(t) as u64);
        }
    }
    black_box(sum)
}

#[export_name = "workload_b"]
#[inline(never)]
pub fn workload_b(data: &[u32], iters: u32) -> u64 {
    let mut sum: u64 = 0;
    let threshold = 1u32 << 28;
    for _ in 0..iters {
        for &x in data {
            let c1 = x > threshold;
            let c2 = (x & 1) == 0;
            let c3 = x != 33;
            let c4 = (x & 2) == 0;
            let c5 = (x & 4) == 0;

            let mut t: u32;
            if c1 {
                if c2 && c3 {
                    if c4 {
                        t = x.wrapping_add(3);
                    } else {
                        t = x.wrapping_add(3);
                    }
                } else {
                    if c5 {
                        t = x.wrapping_add(3);
                    } else {
                        t = x.wrapping_add(7);
                    }
                }
            } else {
                if c2 {
                    t = x.wrapping_add(3);
                } else if c4 {
                    t = x.wrapping_add(3);
                } else if c5 {
                    t = x.wrapping_add(3);
                } else {
                    t = x.wrapping_add(7);
                }
            }

            if (t & 8) == 0 {
                t ^= t.rotate_left(3);
            } else {
                t ^= t.rotate_right(5);
            }

            sum = sum.wrapping_add(postprocess(t) as u64);
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
    let n = parse_arg_u64("--n", 5_000_000) as usize;
    let iters = parse_arg_u64("--iters", 100) as u32;
    let seed = parse_arg_u64("--seed", 1) as u32;
    let variant = parse_arg_string("--variant", "b");

    let data = make_data(n, seed);
    let start = Instant::now();
    let sum = match variant.as_str() {
        "a" | "A" => workload_a(&data, iters),
        _ => workload_b(&data, iters),
    };
    let elapsed = start.elapsed().as_secs_f64();

    println!("Variant: {}", variant);
    println!("N: {}", n);
    println!("Iters: {}", iters);
    println!("Sum: {}", sum);
    println!("Total Time: {:.6} s", elapsed);
    println!("Throughput: {:.2} iters/s", (n as f64 * iters as f64) / elapsed);
}
