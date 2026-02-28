import pandapower.networks as pn
import pandapower.plotting.plotly as pplotly

net = pn.case14()
bus_trace = pplotly.create_bus_trace(net, buses=[1, 2, 3], color="red", size=20)
fig = pplotly.simple_plotly(net, additional_traces=bus_trace)
print("Total traces:", len(fig.data))
for i, t in enumerate(fig.data):
    name = getattr(t, "name", "")
    print(f"Trace {i}: name={name}")
    if hasattr(t, "marker") and t.marker is not None and hasattr(t.marker, "color"):
        orig_color = getattr(t.marker, "color", None)
        print(f"  color={orig_color}")
