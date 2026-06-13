//! D4 対称性 (8 重) による局面の正規化 (symmetry.py の Rust 移植)。
//!
//! 底面 (x,y) の二面体群 D4 (回転4+鏡映4)。z は不変なので重力を壊さず 76 ラインも
//! 不変。各 z 平面は同じ 16 柱の置換を受けるので、16bit 平面 -> 16bit 平面 の置換表を
//! 事前計算して 64bit を 4 ルックアップで変換する。Python と同一の COL_PERMS 順序。

use std::sync::OnceLock;

pub const NUM_COLUMNS: usize = 16;

/// D4 の 8 元を (x,y) -> (x',y') で定義 (Python の _D4_MAPS と同順)。
fn d4_map(t: usize, x: i32, y: i32) -> (i32, i32) {
    match t {
        0 => (x, y),         // 恒等
        1 => (y, 3 - x),     // 90度回転
        2 => (3 - x, 3 - y), // 180度回転
        3 => (3 - y, x),     // 270度回転
        4 => (3 - x, y),     // x 反転
        5 => (x, 3 - y),     // y 反転
        6 => (y, x),         // 主対角 (転置)
        _ => (3 - y, 3 - x), // 反対角
    }
}

/// COL_PERMS[t][c] = 変換後の柱番号。
pub fn col_perms() -> &'static [[usize; NUM_COLUMNS]; 8] {
    static P: OnceLock<[[usize; NUM_COLUMNS]; 8]> = OnceLock::new();
    P.get_or_init(|| {
        let mut perms = [[0usize; NUM_COLUMNS]; 8];
        for (t, perm) in perms.iter_mut().enumerate() {
            for (c, slot) in perm.iter_mut().enumerate() {
                let (x, y) = ((c % 4) as i32, (c / 4) as i32);
                let (nx, ny) = d4_map(t, x, y);
                *slot = (ny * 4 + nx) as usize;
            }
        }
        perms
    })
}

/// INV_COL_PERMS[t][m] = COL_PERMS[t] で m に写る元の柱 (逆置換)。
pub fn inv_col_perms() -> &'static [[usize; NUM_COLUMNS]; 8] {
    static I: OnceLock<[[usize; NUM_COLUMNS]; 8]> = OnceLock::new();
    I.get_or_init(|| {
        let perms = col_perms();
        let mut inv = [[0usize; NUM_COLUMNS]; 8];
        for t in 0..8 {
            for c in 0..NUM_COLUMNS {
                inv[t][perms[t][c]] = c;
            }
        }
        inv
    })
}

/// 各変換の 16bit 平面置換テーブル PLANE_PERM[t][plane]。
fn plane_perms() -> &'static [Vec<u16>; 8] {
    static T: OnceLock<[Vec<u16>; 8]> = OnceLock::new();
    T.get_or_init(|| {
        let perms = col_perms();
        std::array::from_fn(|t| {
            let bitmap: [u16; NUM_COLUMNS] = std::array::from_fn(|c| 1u16 << perms[t][c]);
            let mut table = vec![0u16; 1 << NUM_COLUMNS];
            for plane in 1..(1usize << NUM_COLUMNS) {
                let low = plane & plane.wrapping_neg();
                let c = low.trailing_zeros() as usize;
                table[plane] = table[plane ^ low] | bitmap[c];
            }
            table
        })
    })
}

/// 64bit ビットボード bb を変換 t で写す (z 平面ごとに同じ列置換)。
pub fn transform_bitboard(bb: u64, t: usize) -> u64 {
    let table = &plane_perms()[t];
    (table[(bb & 0xFFFF) as usize] as u64)
        | ((table[((bb >> 16) & 0xFFFF) as usize] as u64) << 16)
        | ((table[((bb >> 32) & 0xFFFF) as usize] as u64) << 32)
        | ((table[((bb >> 48) & 0xFFFF) as usize] as u64) << 48)
}

/// 局面 (b0,b1) の正規化キーと、それを与える変換 t を返す。
///
/// 8 変換すべてを試し (b0' << 64) | b1' が最小になる形を採用。同じ軌道は同じキー。
/// 返り値の t は「現局面 -> 正規形」へ写す変換。
pub fn canonical(b0: u64, b1: u64) -> (u128, usize) {
    let mut best_key: u128 = u128::MAX;
    let mut best_t = 0usize;
    for t in 0..8 {
        let cand =
            ((transform_bitboard(b0, t) as u128) << 64) | (transform_bitboard(b1, t) as u128);
        if cand < best_key {
            best_key = cand;
            best_t = t;
        }
    }
    (best_key, best_t)
}
