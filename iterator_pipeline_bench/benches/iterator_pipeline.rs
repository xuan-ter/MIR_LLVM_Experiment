#![feature(test)]

extern crate test;

use std::hint::black_box;
use test::Bencher;

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

#[bench]
fn easy_case(b: &mut Bencher) {
    const LEN: usize = 16384;
    const ROUNDS: u32 = 32;
    const ALPHA: u32 = 17;
    const BETA: u32 = 31;
    const C: u32 = 7;

    let a = make_data(LEN, 0x1234_5678);
    let b_in = make_data(LEN, 0xDEAD_BEEF);

    b.bytes = (LEN as u64) * 8u64 * (ROUNDS as u64);
    b.iter(|| {
        let sum = kernel_easy(
            black_box(&a),
            black_box(&b_in),
            ROUNDS,
            ALPHA,
            BETA,
            C,
        );
        black_box(sum);
    });
}

#[bench]
fn mir_dependent_case(b: &mut Bencher) {
    const LEN: usize = 16384;
    const ROUNDS: u32 = 32;
    const ALPHA: u32 = 17;
    const BETA: u32 = 31;
    const C: u32 = 7;

    let a = make_data(LEN, 0xCAFEBABE);
    let b_in = make_data(LEN, 0x0BAD_F00D);

    b.bytes = (LEN as u64) * 8u64 * (ROUNDS as u64);
    b.iter(|| {
        let sum = kernel_mir_dependent(
            black_box(&a),
            black_box(&b_in),
            ROUNDS,
            ALPHA,
            BETA,
            C,
        );
        black_box(sum);
    });
}
