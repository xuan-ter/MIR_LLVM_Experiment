#![feature(test)]

extern crate test;

use std::hint::black_box;
use test::Bencher;

use trait_test::{kernel_easy, kernel_mir_dependent, LayeredOp, SimpleOp};

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
    const LEN: usize = 4096;
    const ROUNDS: u32 = 64;

    let data = make_data(LEN, 0x1234_5678);
    let op = SimpleOp { seed: 0xA5A5_5A5A };

    b.bytes = (LEN as u64) * 4u64 * (ROUNDS as u64);
    b.iter(|| {
        let sum = kernel_easy(black_box(&op), black_box(&data), ROUNDS);
        black_box(sum);
    });
}

#[bench]
fn mir_dependent_case(b: &mut Bencher) {
    const LEN: usize = 4096;
    const ROUNDS: u32 = 64;

    let data = make_data(LEN, 0xDEAD_BEEF);
    let op = LayeredOp { seed: 0x1357_9BDF };

    b.bytes = (LEN as u64) * 4u64 * (ROUNDS as u64);
    b.iter(|| {
        let sum = kernel_mir_dependent(black_box(&op), black_box(&data), ROUNDS);
        black_box(sum);
    });
}

