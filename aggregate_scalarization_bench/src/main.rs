use std::hint::black_box;

#[derive(Clone, Copy)]
struct Pair {
    x: i32,
    y: i32,
}

#[derive(Clone, Copy)]
struct Inner {
    a: i32,
    b: i32,
}

#[derive(Clone, Copy)]
struct Outer {
    left: Inner,
    right: Inner,
}

#[inline(never)]
fn bench_a(n: i32) -> i32 {
    let mut p = Pair { x: 1, y: 2 };
    let mut acc: i32 = 0;
    for i in 0..n {
        let i = i as i32;
        p.x = p.x.wrapping_add(i);
        p.y = p.y.wrapping_add(i.wrapping_mul(2));
        acc = acc.wrapping_add(p.x.wrapping_sub(p.y));
    }
    acc
}

#[inline(never)]
fn update_x(v: &mut i32, i: i32) {
    *v = v.wrapping_add(i);
}

#[inline(never)]
fn update_y(v: &mut i32, i: i32) {
    *v = v.wrapping_add(i.wrapping_mul(2));
}

#[inline(never)]
fn bench_b(n: i32) -> i32 {
    let mut p = Pair { x: 1, y: 2 };
    let mut acc: i32 = 0;
    for i in 0..n {
        let i = i as i32;
        update_x(&mut p.x, i);
        update_y(&mut p.y, i);
        acc = acc.wrapping_add(p.x.wrapping_sub(p.y));
    }
    acc
}

#[inline(never)]
fn bench_c(n: i32) -> i32 {
    let mut o = Outer {
        left: Inner { a: 1, b: 2 },
        right: Inner { a: 3, b: 4 },
    };
    let mut acc: i32 = 0;
    for i in 0..n {
        let i = i as i32;
        o.left.a = o.left.a.wrapping_add(i);
        o.left.b = o.left.b.wrapping_add(1);
        o.right.a = o.right.a.wrapping_add(i.wrapping_mul(2));
        o.right.b = o.right.b.wrapping_add(3);
        acc = acc
            .wrapping_add(o.left.a.wrapping_add(o.right.a))
            .wrapping_sub(o.left.b.wrapping_add(o.right.b));
    }
    acc
}

fn parse_arg(args: &[String], name: &str, default: &str) -> String {
    let mut i = 0;
    while i + 1 < args.len() {
        if args[i] == name {
            return args[i + 1].clone();
        }
        i += 1;
    }
    default.to_string()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let variant = parse_arg(&args, "--variant", "A");
    let n: i32 = parse_arg(&args, "--n", "50000000").parse().unwrap_or(50_000_000);

    let res = match variant.as_str() {
        "A" | "a" => bench_a(black_box(n)),
        "B" | "b" => bench_b(black_box(n)),
        "C" | "c" => bench_c(black_box(n)),
        _ => bench_a(black_box(n)),
    };
    println!("{}", black_box(res));
}
