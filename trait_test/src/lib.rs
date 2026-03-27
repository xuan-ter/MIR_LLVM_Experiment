pub trait Transform {
    fn transform(&self, x: u32) -> u32;
}

#[derive(Clone, Copy)]
pub struct SimpleOp {
    pub seed: u32,
}

impl Transform for SimpleOp {
    fn transform(&self, x: u32) -> u32 {
        let y = x.wrapping_add(1);
        let z = y.wrapping_mul(2);
        z ^ self.seed
    }
}

#[derive(Clone, Copy)]
pub struct LayeredOp {
    pub seed: u32,
}

impl Transform for LayeredOp {
    fn transform(&self, x: u32) -> u32 {
        let y = x.wrapping_add(1);
        let z = y.wrapping_add(self.seed);
        z ^ 0
    }
}

pub fn apply_easy<T: Transform + ?Sized>(op: &T, x: u32) -> u32 {
    op.transform(x)
}

pub fn wrap_outer<T: Transform + ?Sized>(op: &T, x: u32) -> u32 {
    let y = x.wrapping_add(0);
    wrap_mid(op, y)
}

pub fn wrap_mid<T: Transform + ?Sized>(op: &T, x: u32) -> u32 {
    let y = x ^ 0;
    wrap_inner(op, y)
}

pub fn wrap_inner<T: Transform + ?Sized>(op: &T, x: u32) -> u32 {
    let y = x.wrapping_add(2);
    op.transform(y)
}

pub fn kernel_easy<T: Transform + ?Sized>(op: &T, data: &[u32], rounds: u32) -> u32 {
    let mut sum = 0u32;
    for _ in 0..rounds {
        for &x in data {
            sum = sum.wrapping_add(apply_easy(op, x));
        }
    }
    sum
}

pub fn kernel_mir_dependent<T: Transform + ?Sized>(op: &T, data: &[u32], rounds: u32) -> u32 {
    let mut sum = 0u32;
    for _ in 0..rounds {
        for &x in data {
            sum = sum.wrapping_add(wrap_outer(op, x));
        }
    }
    sum
}

