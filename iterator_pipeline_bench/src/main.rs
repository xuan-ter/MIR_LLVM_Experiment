use std::env;
use std::time::Instant;

use iterator_pipeline_bench::{kernel_easy, kernel_mir_dependent};

fn make_data(len: usize, seed: u32) -> Vec<u32> {
    let mut x = seed;
    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        x = x.wrapping_mul(1664525).wrapping_add(1013904223);
        out.push(x);
    }
    out
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Mode {
    Easy,
    MirDependent,
}

fn parse_mode(s: &str) -> Option<Mode> {
    match s {
        "easy" => Some(Mode::Easy),
        "mir-dependent" => Some(Mode::MirDependent),
        "mir_dependent" => Some(Mode::MirDependent),
        _ => None,
    }
}

fn parse_u64(s: &str) -> Option<u64> {
    if let Some(hex) = s.strip_prefix("0x") {
        u64::from_str_radix(hex, 16).ok()
    } else {
        s.parse::<u64>().ok()
    }
}

fn usage() -> ! {
    eprintln!("Usage:");
    eprintln!("  iterator_pipeline_bench --mode easy|mir-dependent --len <N> --iters <N> --seed <N>");
    std::process::exit(2);
}

fn main() {
    let mut mode: Option<Mode> = None;
    let mut len: usize = 16384;
    let mut iters: u32 = 32;
    let mut seed: u32 = 0x1234_5678;

    let mut args = env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--mode" => {
                let v = args.next().unwrap_or_else(|| usage());
                mode = parse_mode(&v);
                if mode.is_none() {
                    usage();
                }
            }
            "--len" => {
                let v = args.next().unwrap_or_else(|| usage());
                let n = parse_u64(&v).unwrap_or_else(|| usage()) as usize;
                len = n;
            }
            "--iters" => {
                let v = args.next().unwrap_or_else(|| usage());
                let n = parse_u64(&v).unwrap_or_else(|| usage());
                iters = u32::try_from(n).unwrap_or_else(|_| usage());
            }
            "--seed" => {
                let v = args.next().unwrap_or_else(|| usage());
                let n = parse_u64(&v).unwrap_or_else(|| usage());
                seed = u32::try_from(n).unwrap_or_else(|_| usage());
            }
            "-h" | "--help" => usage(),
            _ => usage(),
        }
    }

    let mode = mode.unwrap_or_else(|| usage());

    let a = make_data(len, seed ^ 0xA5A5_5A5A);
    let b = make_data(len, seed ^ 0x5A5A_A5A5);

    let alpha = (seed | 1).wrapping_mul(17);
    let beta = (seed.rotate_left(13) | 1).wrapping_mul(31);
    let c = seed.wrapping_add(7);

    let start = Instant::now();
    let sum = match mode {
        Mode::Easy => kernel_easy(&a, &b, iters, alpha, beta, c),
        Mode::MirDependent => kernel_mir_dependent(&a, &b, iters, alpha, beta, c),
    };
    let elapsed = start.elapsed();

    let secs = elapsed.as_secs_f64();
    let ns_per_iter = if iters == 0 {
        0f64
    } else {
        elapsed.as_nanos() as f64 / (iters as f64)
    };

    let bytes = (len as f64) * 8.0 * (iters as f64);
    let mbps = if secs == 0.0 { 0.0 } else { (bytes / secs) / 1_000_000.0 };

    std::hint::black_box(sum);
    println!(
        "RESULT mode={:?} len={} iters={} ns_per_iter={:.3} mbps={:.3} sum={}",
        mode, len, iters, ns_per_iter, mbps, sum
    );
}

