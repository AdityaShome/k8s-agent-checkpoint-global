.PHONY: install test bench \
        kind-setup demo-build demo-load demo-deploy demo-run demo-kill demo-clean demo \
        helm-lint helm-install help

CLUSTER_NAME := agent-checkpoint
IMAGE_NAME   := agent-checkpoint-demo:latest
NAMESPACE    := default

# ── Development ──────────────────────────────────────────────────────────────

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

bench:
	python benchmarks/overhead.py

# ── KIND cluster + demo ───────────────────────────────────────────────────────

kind-setup:
	@echo "Creating KIND cluster '$(CLUSTER_NAME)'..."
	kind create cluster --name $(CLUSTER_NAME) || true
	kubectl apply -f k8s/pvc.yaml
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/pdb.yaml
	@echo "Cluster ready."

demo-build:
	@echo "Building Docker image $(IMAGE_NAME)..."
	docker build -t $(IMAGE_NAME) .

demo-load:
	@echo "Loading image into KIND cluster '$(CLUSTER_NAME)'..."
	kind load docker-image $(IMAGE_NAME) --name $(CLUSTER_NAME)

demo-deploy:
	kubectl apply -f k8s/deployment.yaml
	@echo "Waiting for pod to start..."
	kubectl rollout status deployment/agent-checkpoint-demo --timeout=60s

demo-run:
	@echo "Streaming pod logs (Ctrl+C to detach)..."
	kubectl logs -f deployment/agent-checkpoint-demo

# Wipe the checkpoint DB and restart the pod — use before each demo run.
demo-reset:
	kubectl exec deployment/agent-checkpoint-demo -- rm -f /data/checkpoints/demo_run.db
	kubectl rollout restart deployment/agent-checkpoint-demo
	kubectl rollout status deployment/agent-checkpoint-demo --timeout=60s
	@echo "Reset complete. Run 'make demo-run' now."

# Force-deletes the running pod. Kubernetes restarts it immediately (Deployment).
# The agent resumes from the last checkpoint.
demo-kill:
	@echo "Force-killing agent pod..."
	kubectl delete pod -l app=agent-checkpoint-demo --force --grace-period=0
	@echo "Pod killed. Kubernetes is restarting it..."
	@echo "Run 'make demo-run' to watch the resume."

demo-clean:
	kubectl delete -f k8s/ --ignore-not-found
	kind delete cluster --name $(CLUSTER_NAME)

# Full end-to-end setup — run once, then use demo-kill + demo-run for the talk.
demo: kind-setup demo-build demo-load demo-deploy
	@echo ""
	@echo "════════════════════════════════════════════════════════"
	@echo "  agent-checkpoint live demo ready"
	@echo "════════════════════════════════════════════════════════"
	@echo ""
	@echo "  Watch agent run:   make demo-run"
	@echo "  Kill mid-run:      make demo-kill   (in another terminal)"
	@echo "  Watch resume:      make demo-run    (agent picks up from checkpoint)"
	@echo "  Tear down:         make demo-clean"
	@echo ""

# ── Helm ─────────────────────────────────────────────────────────────────────

helm-lint:
	helm lint helm/agent-checkpoint/

helm-install:
	helm upgrade --install agent-checkpoint helm/agent-checkpoint/ \
	    --namespace $(NAMESPACE) \
	    --set image.tag=latest

# ── Help ─────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "agent-checkpoint Makefile targets:"
	@echo ""
	@echo "  install       pip install -e .[dev]"
	@echo "  test          pytest tests/"
	@echo "  bench         python benchmarks/overhead.py"
	@echo ""
	@echo "  kind-setup    Create KIND cluster + apply base k8s manifests"
	@echo "  demo-build    Build Docker image"
	@echo "  demo-load     Load image into KIND"
	@echo "  demo-deploy   Deploy the agent Deployment"
	@echo "  demo-run      Stream pod logs"
	@echo "  demo-kill     Force-delete pod (triggers resume demo)"
	@echo "  demo-clean    Tear down cluster and all resources"
	@echo "  demo          Full setup: kind-setup + build + load + deploy"
	@echo ""
	@echo "  helm-lint     Lint the Helm chart"
	@echo "  helm-install  Install/upgrade via Helm"
	@echo ""
