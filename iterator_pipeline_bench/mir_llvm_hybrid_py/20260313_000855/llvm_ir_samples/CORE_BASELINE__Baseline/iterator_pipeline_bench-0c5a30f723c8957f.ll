; ModuleID = 'iterator_pipeline_bench.25c7b69b414218e2-cgu.0'
source_filename = "iterator_pipeline_bench.25c7b69b414218e2-cgu.0"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

; iterator_pipeline_bench::kernel_easy
; Function Attrs: nofree norecurse nosync nounwind nonlazybind memory(argmem: read) uwtable
define noundef i64 @_ZN23iterator_pipeline_bench11kernel_easy17hb4284862b31fe137E(ptr noalias noundef nonnull readonly align 4 captures(none) %a.0, i64 noundef range(i64 0, 2305843009213693952) %a.1, ptr noalias noundef nonnull readonly align 4 captures(none) %b.0, i64 noundef range(i64 0, 2305843009213693952) %b.1, i32 noundef %rounds, i32 noundef %0, i32 noundef %1, i32 noundef %2) unnamed_addr #0 personality ptr @rust_eh_personality {
start:
  %_173.not = icmp eq i32 %rounds, 0
  br i1 %_173.not, label %bb4, label %bb3.lr.ph

bb3.lr.ph:                                        ; preds = %start
  %_0.sroa.0.0.i.i.i = tail call noundef i64 @llvm.umin.i64(i64 %b.1, i64 %a.1)
  %_207.not.i = icmp eq i64 %_0.sroa.0.0.i.i.i, 0
  br i1 %_207.not.i, label %bb4, label %bb3.preheader

bb3.preheader:                                    ; preds = %bb3.lr.ph
  %min.iters.check = icmp samesign ult i64 %_0.sroa.0.0.i.i.i, 8
  %n.vec = and i64 %_0.sroa.0.0.i.i.i, 2305843009213693944
  %broadcast.splatinsert = insertelement <4 x i32> poison, i32 %0, i64 0
  %broadcast.splat = shufflevector <4 x i32> %broadcast.splatinsert, <4 x i32> poison, <4 x i32> zeroinitializer
  %broadcast.splatinsert7 = insertelement <4 x i32> poison, i32 %1, i64 0
  %broadcast.splat8 = shufflevector <4 x i32> %broadcast.splatinsert7, <4 x i32> poison, <4 x i32> zeroinitializer
  %broadcast.splatinsert9 = insertelement <4 x i32> poison, i32 %2, i64 0
  %broadcast.splat10 = shufflevector <4 x i32> %broadcast.splatinsert9, <4 x i32> poison, <4 x i32> zeroinitializer
  %cmp.n = icmp eq i64 %_0.sroa.0.0.i.i.i, %n.vec
  br label %bb3

bb4:                                              ; preds = %"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E.exit.loopexit", %bb3.lr.ph, %start
  %sum.sroa.0.0.lcssa = phi i64 [ 0, %start ], [ 0, %bb3.lr.ph ], [ %_15, %"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E.exit.loopexit" ]
  ret i64 %sum.sroa.0.0.lcssa

bb3:                                              ; preds = %bb3.preheader, %"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E.exit.loopexit"
  %sum.sroa.0.05 = phi i64 [ %_15, %"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E.exit.loopexit" ], [ 0, %bb3.preheader ]
  %iter.sroa.0.04 = phi i32 [ %_18, %"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E.exit.loopexit" ], [ 0, %bb3.preheader ]
  br i1 %min.iters.check, label %bb14.i.preheader, label %vector.body

vector.body:                                      ; preds = %bb3, %vector.body
  %index = phi i64 [ %index.next, %vector.body ], [ 0, %bb3 ]
  %vec.phi = phi <4 x i32> [ %15, %vector.body ], [ zeroinitializer, %bb3 ]
  %vec.phi11 = phi <4 x i32> [ %16, %vector.body ], [ zeroinitializer, %bb3 ]
  %3 = getelementptr inbounds nuw i32, ptr %a.0, i64 %index
  %4 = getelementptr inbounds nuw i32, ptr %b.0, i64 %index
  %5 = getelementptr inbounds nuw i8, ptr %3, i64 16
  %wide.load = load <4 x i32>, ptr %3, align 4, !noalias !3
  %wide.load12 = load <4 x i32>, ptr %5, align 4, !noalias !3
  %6 = getelementptr inbounds nuw i8, ptr %4, i64 16
  %wide.load13 = load <4 x i32>, ptr %4, align 4, !noalias !3
  %wide.load14 = load <4 x i32>, ptr %6, align 4, !noalias !3
  %7 = mul <4 x i32> %wide.load, %broadcast.splat
  %8 = mul <4 x i32> %wide.load12, %broadcast.splat
  %9 = mul <4 x i32> %wide.load13, %broadcast.splat8
  %10 = mul <4 x i32> %wide.load14, %broadcast.splat8
  %11 = add <4 x i32> %vec.phi, %broadcast.splat10
  %12 = add <4 x i32> %vec.phi11, %broadcast.splat10
  %13 = add <4 x i32> %11, %7
  %14 = add <4 x i32> %12, %8
  %15 = add <4 x i32> %13, %9
  %16 = add <4 x i32> %14, %10
  %index.next = add nuw i64 %index, 8
  %17 = icmp eq i64 %index.next, %n.vec
  br i1 %17, label %middle.block, label %vector.body, !llvm.loop !7

middle.block:                                     ; preds = %vector.body
  %bin.rdx = add <4 x i32> %16, %15
  %18 = tail call i32 @llvm.vector.reduce.add.v4i32(<4 x i32> %bin.rdx)
  br i1 %cmp.n, label %"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E.exit.loopexit", label %bb14.i.preheader

bb14.i.preheader:                                 ; preds = %bb3, %middle.block
  %accum.sroa.0.09.i.ph = phi i32 [ 0, %bb3 ], [ %18, %middle.block ]
  %iter.sroa.0.08.i.ph = phi i64 [ 0, %bb3 ], [ %n.vec, %middle.block ]
  br label %bb14.i

bb14.i:                                           ; preds = %bb14.i.preheader, %bb14.i
  %accum.sroa.0.09.i = phi i32 [ %_4.0.i.i.i, %bb14.i ], [ %accum.sroa.0.09.i.ph, %bb14.i.preheader ]
  %iter.sroa.0.08.i = phi i64 [ %_24.i, %bb14.i ], [ %iter.sroa.0.08.i.ph, %bb14.i.preheader ]
  %_24.i = add nuw nsw i64 %iter.sroa.0.08.i, 1
  %_3.i.i.i = getelementptr inbounds nuw i32, ptr %a.0, i64 %iter.sroa.0.08.i
  %_3.i2.i.i = getelementptr inbounds nuw i32, ptr %b.0, i64 %iter.sroa.0.08.i
  %_16.0.val.i = load i32, ptr %_3.i.i.i, align 4, !noalias !3, !noundef !10
  %_16.1.val.i = load i32, ptr %_3.i2.i.i, align 4, !noalias !3, !noundef !10
  %t0.i.i.i = mul i32 %_16.0.val.i, %0
  %t1.i.i.i = mul i32 %_16.1.val.i, %1
  %_9.i.i.i = add i32 %accum.sroa.0.09.i, %2
  %_0.i.i.i = add i32 %_9.i.i.i, %t0.i.i.i
  %_4.0.i.i.i = add i32 %_0.i.i.i, %t1.i.i.i
  %exitcond.not.i = icmp eq i64 %_24.i, %_0.sroa.0.0.i.i.i
  br i1 %exitcond.not.i, label %"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E.exit.loopexit", label %bb14.i, !llvm.loop !11

"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E.exit.loopexit": ; preds = %bb14.i, %middle.block
  %_4.0.i.i.i.lcssa = phi i32 [ %18, %middle.block ], [ %_4.0.i.i.i, %bb14.i ]
  %_18 = add nuw i32 %iter.sroa.0.04, 1
  %_16 = zext i32 %_4.0.i.i.i.lcssa to i64
  %_15 = add i64 %sum.sroa.0.05, %_16
  %exitcond.not = icmp eq i32 %_18, %rounds
  br i1 %exitcond.not, label %bb4, label %bb3
}

; iterator_pipeline_bench::kernel_mir_dependent
; Function Attrs: nofree norecurse nosync nounwind nonlazybind memory(argmem: read) uwtable
define noundef i64 @_ZN23iterator_pipeline_bench20kernel_mir_dependent17hd8095d591764ffd3E(ptr noalias noundef nonnull readonly align 4 captures(none) %a.0, i64 noundef range(i64 0, 2305843009213693952) %a.1, ptr noalias noundef nonnull readonly align 4 captures(none) %b.0, i64 noundef range(i64 0, 2305843009213693952) %b.1, i32 noundef %rounds, i32 noundef %0, i32 noundef %1, i32 noundef %2) unnamed_addr #0 personality ptr @rust_eh_personality {
start:
  %_225.not = icmp eq i32 %rounds, 0
  br i1 %_225.not, label %bb4, label %bb3.lr.ph

bb3.lr.ph:                                        ; preds = %start
  %_0.sroa.0.0.i.i.i = tail call noundef i64 @llvm.umin.i64(i64 %b.1, i64 %a.1)
  %_207.not.i.i.i.i.i.i.i = icmp eq i64 %_0.sroa.0.0.i.i.i, 0
  br i1 %_207.not.i.i.i.i.i.i.i, label %bb4, label %bb3.preheader

bb3.preheader:                                    ; preds = %bb3.lr.ph
  %min.iters.check = icmp samesign ult i64 %_0.sroa.0.0.i.i.i, 8
  %n.vec = and i64 %_0.sroa.0.0.i.i.i, 2305843009213693944
  %broadcast.splatinsert = insertelement <4 x i32> poison, i32 %0, i64 0
  %broadcast.splat = shufflevector <4 x i32> %broadcast.splatinsert, <4 x i32> poison, <4 x i32> zeroinitializer
  %broadcast.splatinsert9 = insertelement <4 x i32> poison, i32 %1, i64 0
  %broadcast.splat10 = shufflevector <4 x i32> %broadcast.splatinsert9, <4 x i32> poison, <4 x i32> zeroinitializer
  %broadcast.splatinsert11 = insertelement <4 x i32> poison, i32 %2, i64 0
  %broadcast.splat12 = shufflevector <4 x i32> %broadcast.splatinsert11, <4 x i32> poison, <4 x i32> zeroinitializer
  %cmp.n = icmp eq i64 %_0.sroa.0.0.i.i.i, %n.vec
  br label %bb3

bb4:                                              ; preds = %"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E.exit.loopexit", %bb3.lr.ph, %start
  %sum.sroa.0.0.lcssa = phi i64 [ 0, %start ], [ 0, %bb3.lr.ph ], [ %_20, %"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E.exit.loopexit" ]
  ret i64 %sum.sroa.0.0.lcssa

bb3:                                              ; preds = %bb3.preheader, %"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E.exit.loopexit"
  %sum.sroa.0.07 = phi i64 [ %_20, %"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E.exit.loopexit" ], [ 0, %bb3.preheader ]
  %iter.sroa.0.06 = phi i32 [ %_23, %"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E.exit.loopexit" ], [ 0, %bb3.preheader ]
  br i1 %min.iters.check, label %bb14.i.i.i.i.i.i.i.preheader, label %vector.body

vector.body:                                      ; preds = %bb3, %vector.body
  %index = phi i64 [ %index.next, %vector.body ], [ 0, %bb3 ]
  %vec.phi = phi <4 x i32> [ %15, %vector.body ], [ zeroinitializer, %bb3 ]
  %vec.phi13 = phi <4 x i32> [ %16, %vector.body ], [ zeroinitializer, %bb3 ]
  %3 = getelementptr inbounds nuw i32, ptr %a.0, i64 %index
  %4 = getelementptr inbounds nuw i32, ptr %b.0, i64 %index
  %5 = getelementptr inbounds nuw i8, ptr %3, i64 16
  %wide.load = load <4 x i32>, ptr %3, align 4, !noalias !12
  %wide.load14 = load <4 x i32>, ptr %5, align 4, !noalias !12
  %6 = getelementptr inbounds nuw i8, ptr %4, i64 16
  %wide.load15 = load <4 x i32>, ptr %4, align 4, !noalias !12
  %wide.load16 = load <4 x i32>, ptr %6, align 4, !noalias !12
  %7 = mul <4 x i32> %wide.load, %broadcast.splat
  %8 = mul <4 x i32> %wide.load14, %broadcast.splat
  %9 = mul <4 x i32> %wide.load15, %broadcast.splat10
  %10 = mul <4 x i32> %wide.load16, %broadcast.splat10
  %11 = add <4 x i32> %vec.phi, %broadcast.splat12
  %12 = add <4 x i32> %vec.phi13, %broadcast.splat12
  %13 = add <4 x i32> %11, %7
  %14 = add <4 x i32> %12, %8
  %15 = add <4 x i32> %13, %9
  %16 = add <4 x i32> %14, %10
  %index.next = add nuw i64 %index, 8
  %17 = icmp eq i64 %index.next, %n.vec
  br i1 %17, label %middle.block, label %vector.body, !llvm.loop !34

middle.block:                                     ; preds = %vector.body
  %bin.rdx = add <4 x i32> %16, %15
  %18 = tail call i32 @llvm.vector.reduce.add.v4i32(<4 x i32> %bin.rdx)
  br i1 %cmp.n, label %"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E.exit.loopexit", label %bb14.i.i.i.i.i.i.i.preheader

bb14.i.i.i.i.i.i.i.preheader:                     ; preds = %bb3, %middle.block
  %accum.sroa.0.09.i.i.i.i.i.i.i.ph = phi i32 [ 0, %bb3 ], [ %18, %middle.block ]
  %iter.sroa.0.08.i.i.i.i.i.i.i.ph = phi i64 [ 0, %bb3 ], [ %n.vec, %middle.block ]
  br label %bb14.i.i.i.i.i.i.i

bb14.i.i.i.i.i.i.i:                               ; preds = %bb14.i.i.i.i.i.i.i.preheader, %bb14.i.i.i.i.i.i.i
  %accum.sroa.0.09.i.i.i.i.i.i.i = phi i32 [ %_0.i1.i.i.i.i.i.i.i.i.i.i.i.i.i, %bb14.i.i.i.i.i.i.i ], [ %accum.sroa.0.09.i.i.i.i.i.i.i.ph, %bb14.i.i.i.i.i.i.i.preheader ]
  %iter.sroa.0.08.i.i.i.i.i.i.i = phi i64 [ %_24.i.i.i.i.i.i.i, %bb14.i.i.i.i.i.i.i ], [ %iter.sroa.0.08.i.i.i.i.i.i.i.ph, %bb14.i.i.i.i.i.i.i.preheader ]
  %_24.i.i.i.i.i.i.i = add nuw nsw i64 %iter.sroa.0.08.i.i.i.i.i.i.i, 1
  %_3.i.i.i.i.i.i.i.i.i = getelementptr inbounds nuw i32, ptr %a.0, i64 %iter.sroa.0.08.i.i.i.i.i.i.i
  %_3.i2.i.i.i.i.i.i.i.i = getelementptr inbounds nuw i32, ptr %b.0, i64 %iter.sroa.0.08.i.i.i.i.i.i.i
  %_16.0.val.i.i.i.i.i.i.i = load i32, ptr %_3.i.i.i.i.i.i.i.i.i, align 4, !noalias !12, !noundef !10
  %_16.1.val.i.i.i.i.i.i.i = load i32, ptr %_3.i2.i.i.i.i.i.i.i.i, align 4, !noalias !12, !noundef !10
  %t0.i.i.i.i.i.i.i.i.i.i.i.i.i.i = mul i32 %_16.0.val.i.i.i.i.i.i.i, %0
  %t1.i.i.i.i.i.i.i.i.i.i.i.i.i.i = mul i32 %_16.1.val.i.i.i.i.i.i.i, %1
  %_9.i.i.i.i.i.i.i.i.i.i.i.i.i.i = add i32 %accum.sroa.0.09.i.i.i.i.i.i.i, %2
  %_0.i.i.i.i.i.i.i.i.i.i.i.i.i.i = add i32 %_9.i.i.i.i.i.i.i.i.i.i.i.i.i.i, %t0.i.i.i.i.i.i.i.i.i.i.i.i.i.i
  %_0.i1.i.i.i.i.i.i.i.i.i.i.i.i.i = add i32 %_0.i.i.i.i.i.i.i.i.i.i.i.i.i.i, %t1.i.i.i.i.i.i.i.i.i.i.i.i.i.i
  %exitcond.not.i.i.i.i.i.i.i = icmp eq i64 %_24.i.i.i.i.i.i.i, %_0.sroa.0.0.i.i.i
  br i1 %exitcond.not.i.i.i.i.i.i.i, label %"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E.exit.loopexit", label %bb14.i.i.i.i.i.i.i, !llvm.loop !35

"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E.exit.loopexit": ; preds = %bb14.i.i.i.i.i.i.i, %middle.block
  %_0.i1.i.i.i.i.i.i.i.i.i.i.i.i.i.lcssa = phi i32 [ %18, %middle.block ], [ %_0.i1.i.i.i.i.i.i.i.i.i.i.i.i.i, %bb14.i.i.i.i.i.i.i ]
  %_23 = add nuw i32 %iter.sroa.0.06, 1
  %_21 = zext i32 %_0.i1.i.i.i.i.i.i.i.i.i.i.i.i.i.lcssa to i64
  %_20 = add i64 %sum.sroa.0.07, %_21
  %exitcond.not = icmp eq i32 %_23, %rounds
  br i1 %exitcond.not, label %bb4, label %bb3
}

; Function Attrs: nounwind nonlazybind uwtable
declare noundef range(i32 0, 10) i32 @rust_eh_personality(i32 noundef, i32 noundef, i64 noundef, ptr noundef, ptr noundef) unnamed_addr #1

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare i64 @llvm.umin.i64(i64, i64) #2

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare i32 @llvm.vector.reduce.add.v4i32(<4 x i32>) #3

attributes #0 = { nofree norecurse nosync nounwind nonlazybind memory(argmem: read) uwtable "probe-stack"="inline-asm" "target-cpu"="x86-64" }
attributes #1 = { nounwind nonlazybind uwtable "probe-stack"="inline-asm" "target-cpu"="x86-64" }
attributes #2 = { nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none) }
attributes #3 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }

!llvm.module.flags = !{!0, !1}
!llvm.ident = !{!2}

!0 = !{i32 8, !"PIC Level", i32 2}
!1 = !{i32 2, !"RtLibUseGOT", i32 1}
!2 = !{!"rustc version 1.96.0-nightly (2d76d9bc7 2026-03-09)"}
!3 = !{!4, !6}
!4 = distinct !{!4, !5, !"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E: %self"}
!5 = distinct !{!5, !"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E"}
!6 = distinct !{!6, !5, !"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17hec1742e3e3d88ed6E: %f"}
!7 = distinct !{!7, !8, !9}
!8 = !{!"llvm.loop.isvectorized", i32 1}
!9 = !{!"llvm.loop.unroll.runtime.disable"}
!10 = !{}
!11 = distinct !{!11, !9, !8}
!12 = !{!13, !15, !16, !18, !19, !21, !22, !24, !25, !27, !28, !30, !31, !33}
!13 = distinct !{!13, !14, !"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17haec4aa0ddb0b6426E: %self"}
!14 = distinct !{!14, !"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17haec4aa0ddb0b6426E"}
!15 = distinct !{!15, !14, !"_ZN111_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..adapters..zip..ZipImpl$LT$A$C$B$GT$$GT$4fold17haec4aa0ddb0b6426E: %f"}
!16 = distinct !{!16, !17, !"_ZN102_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h48b37c7a8df1704eE: %self"}
!17 = distinct !{!17, !"_ZN102_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h48b37c7a8df1704eE"}
!18 = distinct !{!18, !17, !"_ZN102_$LT$core..iter..adapters..zip..Zip$LT$A$C$B$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h48b37c7a8df1704eE: %f"}
!19 = distinct !{!19, !20, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h76be0bc7a53715d1E: %self"}
!20 = distinct !{!20, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h76be0bc7a53715d1E"}
!21 = distinct !{!21, !20, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h76be0bc7a53715d1E: %g"}
!22 = distinct !{!22, !23, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17hd03085df9caf363cE: %self"}
!23 = distinct !{!23, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17hd03085df9caf363cE"}
!24 = distinct !{!24, !23, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17hd03085df9caf363cE: %g"}
!25 = distinct !{!25, !26, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17hbbcea7671477dc7aE: %self"}
!26 = distinct !{!26, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17hbbcea7671477dc7aE"}
!27 = distinct !{!27, !26, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17hbbcea7671477dc7aE: %g"}
!28 = distinct !{!28, !29, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h3a10868c895a00b0E: %self"}
!29 = distinct !{!29, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h3a10868c895a00b0E"}
!30 = distinct !{!30, !29, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h3a10868c895a00b0E: %g"}
!31 = distinct !{!31, !32, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E: %self"}
!32 = distinct !{!32, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E"}
!33 = distinct !{!33, !32, !"_ZN102_$LT$core..iter..adapters..map..Map$LT$I$C$F$GT$$u20$as$u20$core..iter..traits..iterator..Iterator$GT$4fold17h33ba2c9a098a69a3E: %g"}
!34 = distinct !{!34, !8, !9}
!35 = distinct !{!35, !9, !8}
