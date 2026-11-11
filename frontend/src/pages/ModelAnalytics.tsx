import { api } from "../api/client";
import type { MetricMap, ModelReport } from "../api/types";
import { AsyncView, Card, DataQualityBadge, Pill, Table } from "../components/ui";
import { fmtBps, fmtDate, fmtInt, fmtNum, fmtPct, fmtTime } from "../format";
import { useApi } from "../hooks";

function metric(map: MetricMap, key: string): number | null {
  const value = map[key];
  return value === undefined ? null : value;
}

function ModelCard({ report }: { report: ModelReport }) {
  const test = report.test_metrics;
  const periods: [string, MetricMap][] = [
    ["Validation", report.validation_metrics],
    ["Test (held out)", report.test_metrics],
    ["Walk-forward", report.walk_forward_metrics],
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs text-ink-faint">
        <Pill tone={report.beats_baseline ? "gain" : "warn"}>
          {report.beats_baseline
            ? "Beats naive baselines on the test period"
            : "No demonstrated skill over naive baselines"}
        </Pill>
        <DataQualityBadge quality={report.data_quality} />
        <span>
          {report.model_name} · version {report.model_version} · window {report.window} · trained{" "}
          {fmtTime(report.created_at)}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="card-title mb-2">Direction: model vs naive baselines (test period)</p>
          <Table head={["", "Accuracy", "Log loss"]}>
            <tr>
              <td className="table-cell font-medium">Model</td>
              <td className="table-cell num">
                {fmtPct(metric(test, "accuracy"), 1)}{" "}
                <span className="text-xs text-ink-faint">
                  (95% CI {fmtPct(metric(test, "accuracy_ci_low"), 1)} to{" "}
                  {fmtPct(metric(test, "accuracy_ci_high"), 1)})
                </span>
              </td>
              <td className="table-cell num">{fmtNum(metric(test, "log_loss"), 4)}</td>
            </tr>
            <tr>
              <td className="table-cell">Majority class</td>
              <td className="table-cell num">
                {fmtPct(metric(report.baselines, "majority_class_accuracy"), 1)}
              </td>
              <td className="table-cell num">
                {fmtNum(metric(report.baselines, "constant_rate_log_loss"), 4)}
              </td>
            </tr>
            <tr>
              <td className="table-cell">Always up</td>
              <td className="table-cell num">
                {fmtPct(metric(report.baselines, "always_up_accuracy"), 1)}
              </td>
              <td className="table-cell num">—</td>
            </tr>
            <tr>
              <td className="table-cell">Coin flip</td>
              <td className="table-cell num">
                {fmtPct(metric(report.baselines, "coin_flip_accuracy"), 1)}
              </td>
              <td className="table-cell num">—</td>
            </tr>
          </Table>
        </div>

        <div>
          <p className="card-title mb-2">Data periods (in time order, no overlap)</p>
          <Table head={["Split", "From", "To", "Samples", "Events"]}>
            {["train", "validation", "test"].map((name) => {
              const split = report.splits[name];
              return (
                <tr key={name}>
                  <td className="table-cell capitalize">{name}</td>
                  <td className="table-cell">{fmtDate(split?.start)}</td>
                  <td className="table-cell">{fmtDate(split?.end)}</td>
                  <td className="table-cell num">{fmtInt(split?.samples)}</td>
                  <td className="table-cell num">{fmtInt(split?.events)}</td>
                </tr>
              );
            })}
          </Table>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="card-title mb-2">Performance drift across periods</p>
          <Table head={["Period", "Samples", "Accuracy", "ROC AUC", "Brier", "Share up"]}>
            {periods.map(([name, m]) => (
              <tr key={name}>
                <td className="table-cell">{name}</td>
                <td className="table-cell num">{fmtInt(metric(m, "samples"))}</td>
                <td className="table-cell num">{fmtPct(metric(m, "accuracy"), 1)}</td>
                <td className="table-cell num">{fmtNum(metric(m, "roc_auc"), 3)}</td>
                <td className="table-cell num">{fmtNum(metric(m, "brier"), 4)}</td>
                <td className="table-cell num">{fmtPct(metric(m, "share_up"), 1)}</td>
              </tr>
            ))}
          </Table>
        </div>
        <div>
          <p className="card-title mb-2">Magnitude and volatility heads (test period)</p>
          <Table head={["Measure", "Value"]}>
            <tr>
              <td className="table-cell">Mean absolute error</td>
              <td className="table-cell num">{fmtBps(metric(report.magnitude_metrics, "mae"))}</td>
            </tr>
            <tr>
              <td className="table-cell">MAE if always predicting zero</td>
              <td className="table-cell num">
                {fmtBps(metric(report.magnitude_metrics, "mae_predict_zero"))}
              </td>
            </tr>
            <tr>
              <td className="table-cell">Rank correlation (IC)</td>
              <td className="table-cell num">
                {fmtNum(metric(report.magnitude_metrics, "rank_ic"), 3)}
              </td>
            </tr>
            <tr>
              <td className="table-cell">Unusual volatility ROC AUC</td>
              <td className="table-cell num">
                {fmtNum(metric(report.volatility_metrics, "roc_auc"), 3)}
              </td>
            </tr>
            <tr>
              <td className="table-cell">Unusual move threshold</td>
              <td className="table-cell num">{fmtPct(report.high_vol_threshold)}</td>
            </tr>
          </Table>
        </div>
      </div>

      <details className="text-xs text-ink-muted">
        <summary className="cursor-pointer">Limits of these metrics</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {report.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export function ModelAnalytics({ refreshKey }: { refreshKey: number }) {
  const [models, reloadModels] = useApi(api.models, [refreshKey]);
  const [predictions, reloadPredictions] = useApi(
    () => api.predictions({ limit: 30 }),
    [refreshKey],
  );

  return (
    <div className="space-y-4">
      <AsyncView
        result={models}
        reload={reloadModels}
        emptyTitle="No model has been trained"
        emptyHint="Run `tradebot model train` once events and features exist."
      >
        {(rows) => (
          <>
            <Card title="Latest model: evaluation">
              {rows[0] && <ModelCard report={rows[0]} />}
            </Card>
            <Card title="Model versions">
              <Table head={["Version", "Trained", "Window", "Samples", "Test accuracy", "Result"]}>
                {rows.map((r) => (
                  <tr key={r.model_version}>
                    <td className="table-cell num text-xs">{r.model_version}</td>
                    <td className="table-cell text-ink-muted">{fmtTime(r.created_at)}</td>
                    <td className="table-cell">{r.window}</td>
                    <td className="table-cell num">{fmtInt(r.samples_total)}</td>
                    <td className="table-cell num">{fmtPct(metric(r.test_metrics, "accuracy"), 1)}</td>
                    <td className="table-cell">
                      <Pill tone={r.beats_baseline ? "gain" : "warn"}>
                        {r.beats_baseline ? "beats baselines" : "no demonstrated skill"}
                      </Pill>
                    </td>
                  </tr>
                ))}
              </Table>
            </Card>
          </>
        )}
      </AsyncView>

      <Card title="Prediction history (out-of-sample)">
        <AsyncView
          result={predictions}
          reload={reloadPredictions}
          emptyTitle="No predictions stored"
          emptyHint="Predictions are written when a model is trained."
        >
          {(rows) => (
            <Table head={["Predicted at", "Symbol", "Window", "Direction", "P(up)", "Expected", "Confidence", "Model"]}>
              {rows.map((p) => (
                <tr key={p.prediction_id}>
                  <td className="table-cell whitespace-nowrap text-ink-muted">
                    {fmtTime(p.predicted_at)}
                  </td>
                  <td className="table-cell num font-semibold">{p.symbol}</td>
                  <td className="table-cell">{p.window}</td>
                  <td className="table-cell uppercase">{p.direction}</td>
                  <td className="table-cell num">{fmtPct(p.prob_up, 1)}</td>
                  <td className="table-cell num">{fmtBps(p.expected_abnormal_return)}</td>
                  <td className="table-cell num">{fmtPct(p.confidence, 1)}</td>
                  <td className="table-cell text-xs text-ink-faint">{p.model_version}</td>
                </tr>
              ))}
            </Table>
          )}
        </AsyncView>
      </Card>
    </div>
  );
}
