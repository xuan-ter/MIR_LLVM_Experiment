use std::time::Instant;
use std::env;
use tokio::task;

// 一个复杂的异步函数，旨在生成复杂的状态机
// 包含多个 await 点和跨 await 点的变量借用
async fn complex_calculation(depth: usize, mut data: Vec<u64>) -> u64 {
    if depth == 0 {
        return data.iter().sum();
    }

    // 模拟一些计算
    let mid = data.len() / 2;
    let (left, right) = data.split_at_mut(mid); // 切片操作

    // Await point 1: 模拟 I/O 或调度
    task::yield_now().await;

    // 跨 await 点使用变量
    let left_sum = left.iter().sum::<u64>();
    
    // Await point 2
    task::yield_now().await;
    
    let right_sum = right.iter().sum::<u64>();

    // 递归调用（虽然是 async recursion，通常需要 Box，这里我们用循环模拟深度或者展开）
    // 为了简化并避免 Box 开销掩盖 MIR 优化，我们做一些纯计算的 await
    
    let mut result = left_sum + right_sum;
    
    for i in 0..10 {
        // 模拟状态机内部的循环状态
        result = result.wrapping_add(i as u64);
        if i % 3 == 0 {
            task::yield_now().await;
        }
    }

    result
}

// 模拟高并发任务
async fn run_benchmark(task_count: usize, complexity: usize) -> u64 {
    let mut handles = Vec::with_capacity(task_count);

    for i in 0..task_count {
        handles.push(tokio::spawn(async move {
            // 每个任务创建一个包含数据的 Vec，迫使状态机捕获它
            let data: Vec<u64> = (0..100).map(|x| x + i as u64).collect();
            let mut total = 0;
            // 重复调用以增加热度
            for _ in 0..complexity {
                total += complex_calculation(5, data.clone()).await;
            }
            total
        }));
    }

    let mut final_sum = 0;
    for handle in handles {
        final_sum += handle.await.unwrap();
    }
    final_sum
}

#[tokio::main]
async fn main() {
    let args: Vec<String> = env::args().collect();
    let task_count: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(10_000);
    let complexity: usize = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(50);

    println!("Configuration:");
    println!("  Tasks: {}", task_count);
    println!("  Complexity: {}", complexity);

    let start = Instant::now();
    let result = run_benchmark(task_count, complexity).await;
    let duration = start.elapsed();

    println!("Result: {}", result);
    println!("Total Time: {:.4} s", duration.as_secs_f64());
    
    // 计算吞吐量 (Tasks / second)
    let throughput = task_count as f64 / duration.as_secs_f64();
    println!("Throughput: {:.2} tasks/s", throughput);
}
