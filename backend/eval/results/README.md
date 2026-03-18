# Evaluation Results

## Experimental Setup

| Component | Description |
|-----------|-------------|
| Task | Power flow diagnosis and remediation |
| Test systems | IEEE 14-bus (14 buses, 20 lines), IEEE 30-bus (30 buses, 41 lines), IEEE 57-bus (57 buses, 80 lines) |
| Scenarios | 13 per network: 4 non-convergence, 3 voltage, 3 thermal, 2 contingency, 1 normal |
| Tools | pandapower solver, load shedding, generation redispatch, voltage setpoints |
| Model | GPT-4 |
| Voltage limits | 0.95-1.05 p.u. |
| Thermal limit | 100% loading |

## Metrics

| Metric | Definition |
|--------|------------|
| Violation | Bus voltage outside [0.95, 1.05] p.u. OR line/transformer loading >100% |
| Feasibility (%) | Power flow solver converges after remediation |
| Repair (%) | Converged AND violations_after ≤ violations_before |
| Violation Reduction | Initial violations -> final violations |
| Tool Calls | Number of tools the agent called to fix the network |
| Latency (s) | Total time for diagnosis + remediation per scenario |

## Baselines

- **Baseline (single-pass)**: GPT-4 with function calling, diagnosis only, no remediation
- **Agentic (repair loop)**: GPT-4 with iterative tool use (diagnose -> act -> verify -> repeat)

---

## Results

### Main Results

| Method | Repair (%) | Feas. (%) | Violations | Tool Calls | Latency (s) |
|--------|------------|-----------|------------|------------|-------------|
| Baseline (single-pass) | N/A | N/A | N/A | 1 | 3.6 |
| Agentic (repair loop) | **84.6** | **87.2** | 497->172 | 23.7 | 177.9 |

### Results by Network

| Network | Scenarios | Repair (%) | Feas. (%) | Violations | Tool Calls | Latency (s) |
|---------|-----------|------------|-----------|------------|------------|-------------|
| IEEE 14-bus | 13 | 100 | 100 | 48->2 | 11.8 | 70.2 |
| IEEE 30-bus | 13 | 92.3 | 100 | 128->35 | 21.9 | 199.5 |
| IEEE 57-bus | 13 | 61.5 | 61.5 | 321->135 | 37.4 | 264.1 |
| **Total** | **39** | **84.6** | **87.2** | **497->172** | **23.7** | **177.9** |

### Results by Category

| Category | Scenarios | Repair (%) | Tool Calls |
|----------|-----------|------------|-----------|
| Non-convergence | 12 | 83.3 | 28.5 |
| Voltage | 9 | 77.8 | 25.7 |
| Thermal | 9 | 77.8 | 22.7 |
| Contingency | 6 | 100 | 14.0 |
| Normal | 3 | 100 | 20.7 |

### Baseline Component Detection

| Network | Precision (%) | Recall (%) | F1 (%) |
|---------|---------------|------------|--------|
| IEEE 14-bus | 61.5 | 57.7 | 59.0 |
| IEEE 30-bus | 69.2 | 67.9 | 68.5 |
| IEEE 57-bus | 76.9 | 43.4 | 47.2 |
| **Average** | **69.2** | **56.3** | **58.2** |

*Measures baseline's ability to identify buses with voltage violations. Limitation: line-level (thermal) detection not evaluated.*

---

## Detailed Results: IEEE 14-bus

| Scenario | Category | Initial | Final | Violations | Tool Calls | Latency (s) | Success |
|----------|----------|---------|-------|------------|-------|-------------|---------|
| normal_operation | normal | Conv | Conv | 3->0 | 4 | 10.8 | Yes |
| extreme_load_scaling | nonconv | Div | Conv | 0->0 | 9 | 16.9 | Yes |
| all_generators_removed | nonconv | Conv | Conv | 8->0 | 8 | 35.7 | Yes |
| near_zero_impedance | nonconv | Div | Conv | 0->0 | 18 | 122.9 | Yes |
| disconnected_subnetwork | nonconv | Conv | Conv | 3->0 | 23 | 158.3 | Yes |
| heavy_loading_undervoltage | voltage | Conv | Conv | 7->0 | 31 | 156.6 | Yes |
| excess_generation_overvoltage | voltage | Conv | Conv | 10->0 | 18 | 131.3 | Yes |
| reactive_imbalance | voltage | Conv | Conv | 4->2 | 20 | 133.6 | Yes |
| concentrated_loading | thermal | Conv | Conv | 2->0 | 4 | 28.9 | Yes |
| reduced_thermal_limits | thermal | Conv | Conv | 3->0 | 4 | 29.2 | Yes |
| topology_redirection | thermal | Conv | Conv | 2->0 | 5 | 24.7 | Yes |
| line_contingency_overload | conting | Conv | Conv | 3->0 | 5 | 29.2 | Yes |
| trafo_contingency_voltage | conting | Conv | Conv | 3->0 | 4 | 33.8 | Yes |

## Detailed Results: IEEE 30-bus

| Scenario | Category | Initial | Final | Violations | Tool Calls | Latency (s) | Success |
|----------|----------|---------|-------|------------|-------|-------------|---------|
| normal_operation | normal | Conv | Conv | 1->0 | 6 | 16.2 | Yes |
| extreme_load_scaling | nonconv | Div | Conv | 0->3 | 28 | 269.7 | Yes |
| all_generators_removed | nonconv | Conv | Conv | 33->3 | 49 | 472.4 | Yes |
| near_zero_impedance | nonconv | Div | Conv | 0->1 | 23 | 99.7 | Yes |
| disconnected_subnetwork | nonconv | Conv | Conv | 8->0 | 30 | 234.4 | Yes |
| heavy_loading_undervoltage | voltage | Conv | Conv | 44->19 | 29 | 367.4 | Yes |
| excess_generation_overvoltage | voltage | Conv | Conv | 14->13 | 21 | 266.2 | Yes |
| reactive_imbalance | voltage | Div | Conv | 0->3 | 23 | 183.2 | Yes |
| concentrated_loading | thermal | Conv | Conv | 20->3 | 18 | 233.8 | Yes |
| reduced_thermal_limits | thermal | Conv | Conv | 3->4 | 18 | 147.7 | No |
| topology_redirection | thermal | Conv | Conv | 3->0 | 16 | 127.9 | Yes |
| line_contingency_overload | conting | Conv | Conv | 1->0 | 18 | 149.1 | Yes |
| trafo_contingency_voltage | conting | Conv | Conv | 1->0 | 5 | 35.4 | Yes |

## Detailed Results: IEEE 57-bus

| Scenario | Category | Initial | Final | Violations | Tool Calls | Latency (s) | Success |
|----------|----------|---------|-------|------------|-------|-------------|---------|
| normal_operation | normal | Conv | Conv | 39->2 | 52 | 386.4 | Yes |
| extreme_load_scaling | nonconv | Div | Div | 0->0 | 40 | 198.4 | No |
| all_generators_removed | nonconv | Div | Conv | 0->0 | 34 | 114.2 | Yes |
| near_zero_impedance | nonconv | Div | Conv | 0->0 | 62 | 670.6 | Yes |
| disconnected_subnetwork | nonconv | Conv | Div | 39->0 | 18 | 95.2 | No |
| heavy_loading_undervoltage | voltage | Div | Div | 0->0 | 34 | 215.9 | No |
| excess_generation_overvoltage | voltage | Conv | Conv | 47->33 | 32 | 144.1 | Yes |
| reactive_imbalance | voltage | Div | Div | 0->0 | 23 | 145.1 | No |
| concentrated_loading | thermal | Conv | Div | 40->0 | 39 | 191.3 | No |
| reduced_thermal_limits | thermal | Conv | Conv | 39->21 | 43 | 515.4 | Yes |
| topology_redirection | thermal | Conv | Conv | 39->10 | 57 | 422.7 | Yes |
| line_contingency_overload | conting | Conv | Conv | 39->31 | 23 | 126.4 | Yes |
| trafo_contingency_voltage | conting | Conv | Conv | 39->38 | 29 | 207.9 | Yes |

---

## Latency Statistics

| Pipeline | Mean (s) | Median (s) | Min (s) | Max (s) |
|----------|----------|------------|---------|---------|
| Baseline | 3.6 | 3.4 | 1.7 | 6.1 |
| Agentic (14-bus) | 70.2 | 33.8 | 10.8 | 158.3 |
| Agentic (30-bus) | 199.5 | 183.2 | 16.2 | 472.4 |
| Agentic (57-bus) | 264.1 | 198.4 | 95.2 | 670.6 |

---

## Scalability

| Metric | 14-bus | 30-bus | 57-bus |
|--------|--------|--------|--------|
| Repair (%) | 100 | 92.3 | 61.5 |
| Avg Latency (s) | 70.2 | 199.5 | 264.1 |
| Avg Tool Calls | 11.8 | 21.9 | 37.4 |

---

## Failure Analysis

**IEEE 30-bus (1 failure):**
- `reduced_thermal_limits`: Converged but violations increased (3->4). Insufficient control actions to resolve hard thermal constraints.

**IEEE 57-bus (5 failures):**
- `extreme_load_scaling`: Network divergent, agent could not restore convergence.
- `disconnected_subnetwork`: Agent actions caused previously converged network to diverge.
- `heavy_loading_undervoltage`: Network divergent, agent could not restore convergence.
- `reactive_imbalance`: Network divergent, agent could not restore convergence.
- `concentrated_loading`: Agent actions caused previously converged network to diverge.

**Pattern:** Larger networks have more interdependent components. Fixing one issue can create new problems elsewhere.

---

## Figures

**Figure 1: Repair Rate by Failure Category**
![Repair Rate by Category](figures/fig1_repair_by_category.png)

**Figure 2: Latency Distribution**
![Latency Distribution](figures/fig2_latency_distribution.png)

**Figure 3: Scaling Analysis**
![Scaling Analysis](figures/fig3_scaling_analysis.png)

**Figure 4: Baseline Component Detection**
![Baseline Detection](figures/fig4_baseline_detection.png)

**Figure 5: Violation Reduction**
![Violation Reduction](figures/fig5_violation_reduction.png)

---

## Raw Data

- `full_eval_case14.json`
- `full_eval_case30.json`
- `full_eval_case57.json`
