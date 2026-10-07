# H-Acid: market notes for the reference implementation

* **Chemical:** 1-amino-8-naphthol-3,6-disulfonic acid (H酸), CAS 90-20-0. HS 2922.21 (shared with J-acid, γ-acid).
* **Route:** naphthalene → sulfonation (sulfuric acid/oleum) → nitration (nitric acid) → reduction →
  alkali fusion (caustic soda) → acidification. The nitration and sulfonation steps are hazardous.
  Under a Ministry of Emergency Management catalogue (2024), batch nitration had to be converted to
  continuous processes by Mar 2026.
* **Use:** coupling component of reactive dyes (broker notes put H-Acid at 30–50% of reactive dye
  cost); also acid and direct dyes.
* **Supply:** nominal capacity is roughly 80–100 kt/yr, but effective capacity was below 60 kt in 2025
  (Runtu, cited by several brokers). Production is concentrated in a few plants (registry:
  `data/metadata/producers.csv`).
* **Trade:** China exported about 20 kt in 2024, ~53% of it to India (Huaon, citing customs).

## Documented episodes (see the site's History page for the computed forensics)

| period | what happened | price evidence |
|---|---|---|
| Apr–Jul 2025 | 亚东 (Wuhai) fire in April and second accident in June; 楚源 rectification; 裕源 shutdown | Baiinfo ¥36,500 (early Apr) → ¥41,750 (mid-May) → ¥44,000 (24 Jun) |
| Mar–Apr 2026 | 利元科技 nitration-workshop explosion (19 Mar); nitration deadline end-Mar | ¥40,250 (8 Feb) → ¥47,500 (20 Mar) → ¥61,000 (9 Apr) → ¥65,000 (14 Apr) |
| Jul–Sep 2026 | one-day 31% jump on 28 Jul (Baiinfo); producer 大柴旦和信 +64% to ¥100k; peak-season restocking with low buyer inventories; producers lift ex-works quotes to ¥150k | Baiinfo ¥61,000 (27 Jul) → ¥80,000 (28 Jul); SCI99 ¥95/kg (28 Aug); Baiinfo ~¥130k (mid-Sep) → ¥150,000 (30 Sep) |

Prices between 14 Apr and 27 Jul 2026 are not verified in public sources this project can cite
(the 27 Jul figure implies the price eased from ¥65k to ¥61k); the site leaves that stretch as an
unobserved gap rather than interpolating.
