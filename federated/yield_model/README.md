# Federated Tomato Yield Prediction — Final Model Package

## Phase objective

This phase implemented Federated Learning for tomato-yield prediction at the Fog layer. The purpose was to allow several agricultural zones to collaborate on one global prediction model without sending their raw plot data to a central server. Each Fog client trained locally, while only model updates were aggregated and redistributed.

## Data preparation

The Carucci industrial-tomato dataset was converted into a plot-level learning table containing 100 unique plots from 32 experiments. A plot was identified using `ID + REP`, which preserved all experimental replicates. Soil and experiment information were merged by experiment ID, physiology was aggregated per plot, and irrigation, phenology, and weather were summarized for each growing season. The plots were divided into nine year-based clients to simulate non-IID Fog zones. The yield target was normalized to tonnes per hectare using the source unit `q` and a conversion factor of `0.1`. The final unit interpretation should still be confirmed from the dataset documentation.

## Models and evaluation

The experiments compared centralized baselines, local-only learning, FedAvg, FedProx, event-driven FedProx, and event-driven FedProx with compressed updates. Each method was evaluated across 30 paired random seeds using MAE, RMSE, R², communication traffic, and client-participation rate. Bootstrap confidence intervals and paired Wilcoxon signed-rank tests with Holm correction were used to reduce the risk of selecting a model from one lucky split. FedAvg was selected as the final federated model because it achieved the lowest repeated mean MAE among the federated methods, approximately `11.00 t/ha`, with a mean R² of approximately `0.62`.

## Communication results

Standard FedAvg and FedProx used about `2.35 MB` of model-update traffic per experiment. Event-driven FedProx reduced average traffic to about `0.91 MB` by activating only clients with new data, high local error, or excessive participation staleness. Adding top-k and int8 compression reduced traffic further to about `0.30 MB`, but prediction error increased. This demonstrated the expected trade-off between predictive accuracy and communication efficiency.

## Package contents

- `global_yield_model.pt`: selected global federated model.
- `imputer.joblib`: missing-value preprocessing.
- `scaler.joblib`: numeric feature scaling.
- `encoder.joblib`: categorical feature encoder.
- `preprocessor_schema.json`: expected input features and target scaling.
- `model_config.json`: neural-network configuration.
- `model_card.json`: model selection, dataset, metrics, and limitations.
- `results.json`: detailed result for the representative model run.
- `fog_request_example.json`: example Fog input payload.
- `fog_response_example.json`: example yield-prediction response.

## Integration target

The Fog service should load this package, preprocess locally aggregated agricultural features, and return a yield estimate with its model version and unit. The predicted yield can then be logged locally and sent as a summary to the Cloud. The Cloud and Digital Twin may later use these summaries for long-term trend analysis, production planning, and agricultural what-if simulations. Raw plot or sensor records should remain local to the Fog client.

## Scope and limitations

This package is sufficient for model loading and Fog integration. The separate statistical CSV files are not required at runtime, but they should be preserved for the internship report, reproducibility, and paper results. The current clients represent experimental years rather than deployed farms, no differential privacy or secure aggregation is implemented, and target-hardware latency still needs to be measured.
