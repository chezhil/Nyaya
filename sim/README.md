# Evaluation inputs

`simulate(ctx, params)` uses `suite_tag="eval"` by default and samples the requested
7,500 normal, 1,800 displaced and 700 syndicate payments from the whole file.
`syndicate_forward` rows do not count toward the suite. Missing files and
insufficient populations raise errors; there is no fallback to training data.
The data owner must generate this independent dataset with a fresh seed, unseen
by training, calibration and tuning. The tag alone cannot prove independence.

`pareto(ctx, params)` is the sensitivity path. It defaults to `tag="v2"` and uses
Model A's authoritative held-out test split. `counts` can reduce sample sizes for
development. Each point reports baseline metrics valued under that point's
policy; the top-level baselines describe the base policy only.

`redteam(ctx, params)` defaults to the whole `eval` file for its `base` variant
syndicate rows, and whole `redteam_smurf`, `redteam_device_spoof` and
`redteam_slow_drip` files for attacks. Override the base file through `base_tag`
or `suite_tag`, and attack files through `tags`. The general training-data tag
does not select the red-team base. Detection counts HOLD or REVIEW.

Local hook tests use explicitly fake bundles and hand-built synthetic fixtures:

```sh
python -m unittest discover -s sim/tests -v
```

Their expectations are not model metrics. Real evaluation results require the
trained artifacts and authorized runs in the LinuxONE `notebook` container.
