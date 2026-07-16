// static/app.js

document.addEventListener("DOMContentLoaded", () => {
    // Config values
    const colors = {
        group: "#ec4899",
        person: "#10b981",
        default: "#94a3b8"
    };

    // Grab UI Elements
    const svg = d3.select("#graph-svg");
    const container = d3.select("#canvas-container");
    const searchInput = document.getElementById("search-input");
    const filterMembership = document.getElementById("filter-membership");
    const filterIntroduction = document.getElementById("filter-introduction");
    const resetButton = document.getElementById("reset-button");
    const detailCard = document.getElementById("detail-card");
    const closeCardBtn = document.getElementById("close-card-btn");
    const cardName = document.getElementById("card-name");
    const cardTypeBadge = document.getElementById("card-type-badge");
    const cardMetadata = document.getElementById("card-metadata");
    const cardContexts = document.getElementById("card-contexts");

    let width = container.node().clientWidth;
    let height = container.node().clientHeight;

    // Set SVG size
    svg.attr("width", width).attr("height", height);

    // Zoom container
    const g = svg.append("g");

    // Apply D3 Zoom
    const zoom = d3.zoom()
        .scaleExtent([0.1, 8])
        .on("zoom", (event) => {
            g.attr("transform", event.transform);
        });

    svg.call(zoom);

    // D3 Force Simulation Setup
    const simulation = d3.forceSimulation()
        .force("link", d3.forceLink().id(d => d.id).distance(100))
        .force("charge", d3.forceManyBody().strength(-200))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collision", d3.forceCollide().radius(30));

    // Graph Data Holders
    let allNodes = [];
    let allLinks = [];
    let linkElements, nodeElements;

    // Load Graph Data
    fetch("/api/graph")
        .then(response => response.json())
        .then(data => {
            allNodes = data.nodes;
            allLinks = data.edges;

            // Draw initial graph
            updateGraph();
            setupSearch();
            setupFilters();
        })
        .catch(err => console.error("Error loading graph data:", err));

    function updateGraph() {
        // Clear previous elements
        g.selectAll("*").remove();

        // Arrow markers for directed edges
        g.append("defs").selectAll("marker")
            .data(["introduction", "membership"])
            .enter().append("marker")
            .attr("id", d => `arrow-${d}`)
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 22) // Place arrow head on node perimeter
            .attr("refY", 0)
            .attr("markerWidth", 6)
            .attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path")
            .attr("fill", d => d === "membership" ? "#ec4899" : "#94a3b8")
            .attr("d", "M0,-5L10,0L0,5");

        // Filter links according to checkbox settings
        const showMembership = filterMembership.checked;
        const showIntroduction = filterIntroduction.checked;

        const filteredLinks = allLinks.filter(l => {
            if (l.type === "membership" && !showMembership) return false;
            if (l.type === "introduction" && !showIntroduction) return false;
            return true;
        });

        // Filter nodes (keep only nodes referenced by active links, or all nodes if no filter is active)
        const activeNodeIds = new Set();
        filteredLinks.forEach(l => {
            activeNodeIds.add(typeof l.source === 'object' ? l.source.id : l.source);
            activeNodeIds.add(typeof l.target === 'object' ? l.target.id : l.target);
        });

        const filteredNodes = allNodes.filter(n => activeNodeIds.has(n.id));

        // 1. Draw Links
        linkElements = g.append("g")
            .attr("class", "links")
            .selectAll("line")
            .data(filteredLinks)
            .enter().append("line")
            .attr("class", d => `link ${d.type}`)
            .attr("marker-end", d => `url(#arrow-${d.type})`);

        // 2. Draw Nodes
        nodeElements = g.append("g")
            .attr("class", "nodes")
            .selectAll(".node")
            .data(filteredNodes)
            .enter().append("g")
            .attr("class", "node")
            .call(drag(simulation))
            .on("click", handleNodeClick)
            .on("mouseover", handleMouseOver)
            .on("mouseout", handleMouseOut);

        // Append circles to nodes
        nodeElements.append("circle")
            .attr("r", d => d.type === "group" ? 10 : 7)
            .attr("fill", d => d.type === "group" ? colors.group : colors.person)
            .style("filter", d => {
                // Drop-shadow glow effects
                const color = d.type === "group" ? colors.group : colors.person;
                return `drop-shadow(0px 0px 4px ${color}80)`;
            });

        // Append Labels to nodes
        nodeElements.append("text")
            .attr("dx", 12)
            .attr("dy", ".35em")
            .text(d => d.name);

        // Bind data to simulation forces
        simulation.nodes(filteredNodes);
        simulation.force("link").links(filteredLinks);
        simulation.alpha(1).restart();

        // Ticker update on simulation run
        simulation.on("tick", () => {
            linkElements
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);

            nodeElements
                .attr("transform", d => `translate(${d.x},${d.y})`);
        });
    }

    // Node click handler (Displays detail card)
    function handleNodeClick(event, d) {
        event.stopPropagation();
        
        cardName.textContent = d.name;
        cardTypeBadge.textContent = d.type;
        cardTypeBadge.style.backgroundColor = d.type === "group" ? colors.group + "40" : colors.person + "40";
        cardTypeBadge.style.color = d.type === "group" ? colors.group : colors.person;

        // Set metadata tags
        cardMetadata.innerHTML = "";
        const meta = d.metadata || [];
        if (meta.length > 0) {
            meta.forEach(tag => {
                const span = document.createElement("span");
                span.className = "tag";
                span.textContent = tag;
                cardMetadata.appendChild(span);
            });
        } else {
            cardMetadata.textContent = "None";
        }

        // Set context tags
        cardContexts.innerHTML = "";
        const ctxs = d.contexts || [];
        if (ctxs.length > 0) {
            ctxs.forEach(tag => {
                const span = document.createElement("span");
                span.className = "tag";
                span.textContent = tag;
                cardContexts.appendChild(span);
            });
        } else {
            cardContexts.textContent = "None";
        }

        detailCard.style.display = "block";
    }

    // Highlights connections on mouse over
    function handleMouseOver(event, d) {
        // Collect connected nodes
        const connectedNodes = new Set();
        connectedNodes.add(d.id);

        linkElements.each(function(l) {
            const sourceId = l.source.id;
            const targetId = l.target.id;
            if (sourceId === d.id) {
                connectedNodes.add(targetId);
            } else if (targetId === d.id) {
                connectedNodes.add(sourceId);
            }
        });

        // Apply highlights & dim others
        nodeElements.classed("dimmed", n => !connectedNodes.has(n.id));
        linkElements.classed("dimmed", l => l.source.id !== d.id && l.target.id !== d.id);
    }

    function handleMouseOut() {
        nodeElements.classed("dimmed", false);
        linkElements.classed("dimmed", false);
    }

    // Search bar functionality
    function setupSearch() {
        searchInput.addEventListener("input", (e) => {
            const query = e.target.value.toLowerCase().trim();
            if (!query) {
                nodeElements.classed("highlighted", false).classed("dimmed", false);
                linkElements.classed("dimmed", false);
                return;
            }

            // Find matching nodes
            const matches = new Set();
            nodeElements.each(function(d) {
                if (d.name.toLowerCase().includes(query)) {
                    matches.add(d.id);
                }
            });

            // Dim everything except matched nodes
            nodeElements.classed("highlighted", d => matches.has(d.id));
            nodeElements.classed("dimmed", d => !matches.has(d.id));
            linkElements.classed("dimmed", true);
        });
    }

    // Filter checkbox binds
    function setupFilters() {
        filterMembership.addEventListener("change", updateGraph);
        filterIntroduction.addEventListener("change", updateGraph);
        
        resetButton.addEventListener("click", () => {
            // Reset filters
            filterMembership.checked = true;
            filterIntroduction.checked = true;
            searchInput.value = "";
            detailCard.style.display = "none";
            
            updateGraph();

            // Reset zoom transform
            svg.transition().duration(750).call(
                zoom.transform,
                d3.zoomIdentity
            );
        });

        closeCardBtn.addEventListener("click", () => {
            detailCard.style.display = "none";
        });
    }

    // Node Drag mechanics
    function drag(sim) {
        function dragstarted(event) {
            if (!event.active) sim.alphaTarget(0.3).restart();
            event.subject.fx = event.subject.x;
            event.subject.fy = event.subject.y;
        }

        function dragged(event) {
            event.subject.fx = event.x;
            event.subject.fy = event.y;
        }

        function dragended(event) {
            if (!event.active) sim.alphaTarget(0);
            event.subject.fx = null;
            event.subject.fy = null;
        }

        return d3.drag()
            .on("start", dragstarted)
            .on("drag", dragged)
            .on("end", dragended);
    }

    // Handle window resizing
    window.addEventListener("resize", () => {
        width = container.node().clientWidth;
        height = container.node().clientHeight;
        svg.attr("width", width).attr("height", height);
        simulation.force("center", d3.forceCenter(width / 2, height / 2));
        simulation.alpha(0.3).restart();
    });
});
