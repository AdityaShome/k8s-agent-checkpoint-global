{{/*
Expand the name of the chart.
*/}}
{{- define "agent-checkpoint.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "agent-checkpoint.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "agent-checkpoint.labels" -}}
helm.sh/chart: {{ include "agent-checkpoint.name" . }}-{{ .Chart.Version }}
{{ include "agent-checkpoint.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "agent-checkpoint.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agent-checkpoint.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
