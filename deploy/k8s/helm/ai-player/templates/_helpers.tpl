{{/*
Expand the name of the chart.
*/}}
{{- define "ai-player.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "ai-player.fullname" -}}
{{- .Values.aiPlayer.name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "ai-player.labels" -}}
helm.sh/chart: {{ include "ai-player.name" . }}
{{ include "ai-player.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "ai-player.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ai-player.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: ai-player
{{- end }}

{{/*
Database URL (SQLAlchemy requires postgresql://, not postgres://)
*/}}
{{- define "ai-player.databaseUrl" -}}
{{- if .Values.aiPlayer.database.external -}}
postgresql://{{ .Values.aiPlayer.database.username }}:{{ .Values.aiPlayer.database.password }}@{{ .Values.aiPlayer.database.host }}:{{ .Values.aiPlayer.database.port }}/{{ .Values.aiPlayer.database.name }}
{{- else -}}
postgresql://{{ .Values.postgresql.auth.username }}:{{ .Values.postgresql.auth.password }}@{{ .Release.Name }}-postgresql:5432/{{ .Values.postgresql.auth.database }}
{{- end -}}
{{- end }}
