; KERN proof over real third-party code:
;   andrewrk/zig-general-purpose-allocator, gpda.zig:1065
;   fn isAligned(addr: usize, alignment: usize) bool {
;       const aligned_addr = (addr & ~(alignment - 1));
;       return aligned_addr == addr;
;   }
; Claim: for EVERY power-of-two alignment > 0 and EVERY 32-bit addr,
;        (addr & ~(alignment-1)) == addr   <=>   addr % alignment == 0
(set-logic QF_BV)
(declare-const addr (_ BitVec 32))
(declare-const alignment (_ BitVec 32))
; alignment is non-zero and a power of two
(assert (and (not (= alignment #x00000000))
             (= (bvand alignment (bvsub alignment #x00000001)) #x00000000)))
; negate the equivalence: ask Z3 for a counterexample to the claim
(assert (not (= (= (bvand addr (bvnot (bvsub alignment #x00000001))) addr)
               (= (bvurem addr alignment) #x00000000))))
(check-sat)
