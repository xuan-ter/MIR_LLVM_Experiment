use std::future::Future;
use std::hint::black_box;
use std::pin::Pin;
use std::task::{Context, Poll, RawWaker, RawWakerVTable, Waker};

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

fn noop_waker() -> Waker {
    unsafe fn clone(_: *const ()) -> RawWaker {
        RawWaker::new(std::ptr::null(), &VTABLE)
    }
    unsafe fn wake(_: *const ()) {}
    unsafe fn wake_by_ref(_: *const ()) {}
    unsafe fn drop(_: *const ()) {}

    static VTABLE: RawWakerVTable = RawWakerVTable::new(clone, wake, wake_by_ref, drop);

    unsafe { Waker::from_raw(RawWaker::new(std::ptr::null(), &VTABLE)) }
}

fn block_on<F: Future>(mut fut: F) -> F::Output {
    let waker = noop_waker();
    let mut cx = Context::from_waker(&waker);
    let mut fut = unsafe { Pin::new_unchecked(&mut fut) };
    loop {
        match fut.as_mut().poll(&mut cx) {
            Poll::Ready(v) => return v,
            Poll::Pending => {}
        }
    }
}

struct YieldOnce {
    done: bool,
    value: i32,
}

impl YieldOnce {
    fn new(value: i32) -> Self {
        Self { done: false, value }
    }
}

impl Future for YieldOnce {
    type Output = i32;

    fn poll(mut self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        if self.done {
            Poll::Ready(self.value)
        } else {
            self.done = true;
            Poll::Pending
        }
    }
}

async fn step_add(x: i32, k: i32) -> i32 {
    let y = YieldOnce::new(x.wrapping_add(k)).await;
    y ^ (k.wrapping_mul(3))
}

async fn linear_chain(mut x: i32, depth: u32) -> i32 {
    let mut i = 0;
    while i < depth {
        let k = (i as i32).wrapping_add(x & 7);
        x = x.wrapping_add(step_add(x, k).await);
        i += 1;
    }
    x
}

async fn branched_chain(mut x: i32, depth: u32) -> i32 {
    let mut i = 0;
    while i < depth {
        let k = (i as i32).wrapping_add((x >> 1) & 7);
        if (x & 1) == 0 {
            x = x.wrapping_add(step_add(x, k).await);
            if (x & 3) == 0 {
                x ^= step_add(x, k ^ 5).await;
            } else {
                x = x.wrapping_sub(step_add(x, k ^ 9).await);
            }
        } else {
            x = x.wrapping_sub(step_add(x, k).await);
            match (x ^ k) & 3 {
                0 => x ^= step_add(x, 1).await,
                1 => x ^= step_add(x, 2).await,
                2 => x ^= step_add(x, 3).await,
                _ => x ^= step_add(x, 4).await,
            }
        }
        i += 1;
    }
    x
}

async fn looped_chain(mut x: i32, n: u32) -> i32 {
    let mut i = 0;
    while i < n {
        x = x.wrapping_add(step_add(x, (i as i32) & 7).await);
        if (x & 7) == 0 {
            x = x.wrapping_add(step_add(x, 11).await);
        } else if (x & 7) == 1 {
            x = x.wrapping_sub(step_add(x, 13).await);
        } else {
            x ^= step_add(x, 17).await;
        }
        i += 1;
    }
    x
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let variant = parse_arg(&args, "--variant", "S");
    let n: u32 = parse_arg(&args, "--n", "200000").parse().unwrap_or(200_000);
    let depth: u32 = parse_arg(&args, "--depth", "8").parse().unwrap_or(8);

    let mut acc: i32 = 0;
    let mut i = 0;
    while i < n {
        let x = black_box(i as i32).wrapping_mul(31).wrapping_add(7);
        let r = match variant.as_str() {
            "S" | "s" => block_on(linear_chain(x, depth)),
            "B" | "b" => block_on(branched_chain(x, depth)),
            "L" | "l" => block_on(looped_chain(x, depth)),
            _ => block_on(linear_chain(x, depth)),
        };
        acc = acc.wrapping_add(black_box(r));
        i += 1;
    }
    println!("{}", black_box(acc));
}
