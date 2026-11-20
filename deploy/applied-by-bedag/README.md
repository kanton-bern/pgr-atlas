# Applied by Bedag, not by Flux

Objects that neither Flux's service account nor the project's users may write, so Bedag
applies them by hand. Flux never sees this folder: it only reads
`deploy/stages/<stage>`.

| File | Objects | Namespace |
|---|---|---|
| [test/alertmanagerconfig.yaml](test/alertmanagerconfig.yaml) | AlertmanagerConfig `pgr-atlas-test` + placeholder Secret | `bedag-cloud-aw3-pgr` |
| [prod/alertmanagerconfig.yaml](prod/alertmanagerconfig.yaml) | AlertmanagerConfig `pgr-atlas-prod` + placeholder Secret | `bedag-cloud-aw3-pgr` |

Written and applied by Bedag; mail delivery verified on both stages.
`bedag-cloud-aw3-pgr` is Bedag's
tenant namespace for the project's subscription; the project's role can't read it.

**What these are:** Bedag's own `AlertmanagerConfig` type
(`observability.bedag.crossplane.io/v1alpha1`), not the Prometheus Operator's
(`monitoring.coreos.com`). It carries a plain Alertmanager configuration
(snake_case keys, as in `alertmanager.yml`) under `spec.alertmanagerConfig`, and
needs a Secret in `spec.secretRef` (here only a placeholder). The route mails
every alert labelled `email="true"` to `alert@skerlak.ch` (monitoring only;
the contact for users is `support@skerlak.ch`); the project's rules set that label on every alert
([prometheusrule.yaml](../stages/base/monitoring/prometheusrule.yaml)).

**Changing one** (more recipients, other timings): edit the file here, PR,
merge, then ask Bedag to apply it again. Git is the source of truth; the maintainers can't
see what is applied. Recipients: a comma-separated list in `to`. Different
recipients per stage: the child route would also need a
`k8s_cluster_name="kb-common-<stage>"` matcher, since nothing else in these
configs tells the stages apart.

What the alerts are and how they fit together:
[docs/monitoring.md](../../docs/monitoring.md).
