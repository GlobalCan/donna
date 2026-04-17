# Golden evals

Frozen goal → expected-behavior pairs, tagged by capability.

Run: `pytest evals/`

Each YAML file is one eval. Schema:
```yaml
id: grounded_refuse_empty_retrieval
description: Grounded mode refuses when retrieval returns no chunks
capability: grounded
setup:
  scope: author_test_empty
  seed_corpus: []
input:
  mode: grounded
  question: "What did X say about Y?"
expect:
  refused: true
  reason_contains: "don't have material"
```

Run the whole set:
```
pytest evals/ -v
```

Add a new eval when you:
 - Catch a real regression after a prompt/code change
 - Observe a repeated failure mode
 - Notice the bot doing the right thing in a surprising case
