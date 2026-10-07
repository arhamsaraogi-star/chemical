# Methodology

The same text is shown on the site's **Methodology** page (`site/index.html`, template
`tpl-methodology`). The formal rules, thresholds and their tests are in
[SPECIFICATION.md](SPECIFICATION.md) §5–§8. Summary:

1. **Five kinds of number:** observed, derived, estimated, inferred and ai-extracted. They are
   stored in `value_kind` and shown as pills on the site.
2. **Price construction:** sources are kept separate; on any date the master value is a tier- and
   confidence-weighted median, with one vote per source family. Values are carried forward for at
   most 45 business days. Longer gaps are left unobserved, and nothing is detected inside them.
3. **Point-in-time:** `known_date = max(economic, information)`. Score, alerts and backtests use
   only what was known. Unknown vintages are excluded. Estimated vintages are allowed only with an
   explicit lag.
4. **Inflections:** a move of ≥5%/5d, ≥10%/20d or ≥20%/60d triggers. Onsets are reported as a
   window built from the start-date sensitivity range and the real observations bracketing the move.
   The fundamental onset is the first supporting event or indicator turn; system detection is the
   first point-in-time alert.
5. **Score:** components (expanding mid-rank percentiles) are averaged within eight signal blocks,
   and blocks are combined with fixed weights. The state comes from the score alone; driver and
   confidence are reported separately. Coverage below 70% caps the state at WATCH.
6. **Events:** decayed pressure (30-day half-life). The last known event is shown separately from
   the residual pressure.
7. **Statistics:** every lead/lag figure, hit rate and lift carries N, labelled exploratory
   (<10), indicative (10–29) or statistically meaningful (≥30).
8. **Analogues:** cosine similarity of block fingerprints against completed earlier inflections.
   Below 65% the site shows "no strong analogue".
9. **Feedstock index:** chain-linked and equal-weighted, because no sourced production
   coefficients exist. It is a price index, not a cost of production.
