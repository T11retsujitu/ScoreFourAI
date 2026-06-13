//! 76 本の勝利ライン生成 (board.py / lines.py の Rust 移植)。
//!
//! セルのインデックス規約は Python 側と完全一致させる (唯一の定義):
//!     index = z * 16 + y * 4 + x      // x,y in 0..3 (基盤), z in 0..3 (高さ)
//!     col   = y * 4 + x               // 柱 0..15
//!     cell  = col + z * 16
//!
//! まず総当たりで全ラインを列挙し、本数が必ず 76 になることを契約テストで保証する。

pub const N: i32 = 4;
pub const NUM_CELLS: usize = 64;

/// 座標 (x, y, z) をセルインデックスへ (Python の cell_index と同一)。
pub fn cell_index(x: i32, y: i32, z: i32) -> usize {
    (z * 16 + y * 4 + x) as usize
}

/// 全 76 本の勝利ラインを、昇順ソートしたセル 4 つ組のベクタで返す。
///
/// 手法は総当たり: 全 64 セルを始点に 26 方向へ 4 マス伸ばし、盤内に収まる組だけ
/// 採用。順逆で 2 度出るのでセル集合で正規化して重複除去。決定的に整列して返す。
pub fn all_lines() -> Vec<[usize; 4]> {
    let mut dirs: Vec<(i32, i32, i32)> = Vec::new();
    for dx in -1..=1 {
        for dy in -1..=1 {
            for dz in -1..=1 {
                if dx == 0 && dy == 0 && dz == 0 {
                    continue;
                }
                dirs.push((dx, dy, dz));
            }
        }
    }

    let mut seen: std::collections::HashSet<[usize; 4]> = std::collections::HashSet::new();
    let mut lines: Vec<[usize; 4]> = Vec::new();
    for x in 0..N {
        for y in 0..N {
            for z in 0..N {
                for &(dx, dy, dz) in &dirs {
                    let mut cells = [0usize; 4];
                    let mut ok = true;
                    let in_range = |v: i32| (0..N).contains(&v);
                    for i in 0..4 {
                        let (cx, cy, cz) = (x + i * dx, y + i * dy, z + i * dz);
                        if !in_range(cx) || !in_range(cy) || !in_range(cz) {
                            ok = false;
                            break;
                        }
                        cells[i as usize] = cell_index(cx, cy, cz);
                    }
                    if ok {
                        let mut key = cells;
                        key.sort_unstable();
                        if seen.insert(key) {
                            lines.push(key);
                        }
                    }
                }
            }
        }
    }
    lines.sort_unstable();
    lines
}

/// 76 ラインのビットマスクと、各セルを通るラインの一覧。
pub struct LineTables {
    // line_masks は段階2 (評価・全局面走査) で使う。段階1 では cell_lines のみ使用。
    #[allow(dead_code)]
    pub line_masks: Vec<u64>,
    /// cell_lines[idx] = セル idx を含むラインマスク (増分勝利判定用)。
    pub cell_lines: Vec<Vec<u64>>,
}

pub fn build_line_tables() -> LineTables {
    let lines = all_lines();
    let mut line_masks: Vec<u64> = Vec::with_capacity(lines.len());
    let mut cell_lines: Vec<Vec<u64>> = vec![Vec::new(); NUM_CELLS];
    for line in &lines {
        let mut mask = 0u64;
        for &idx in line {
            mask |= 1u64 << idx;
        }
        line_masks.push(mask);
        for &idx in line {
            cell_lines[idx].push(mask);
        }
    }
    LineTables {
        line_masks,
        cell_lines,
    }
}
