# ADR-001: 2 bedroom nodes vs 1

## Context
The bedroom sensing zone requires WiFi CSI nodes to detect breathing rate, heart rate proxy, and sleep stages overnight. The question is whether one node is sufficient or whether two nodes provide meaningful improvement.

## Options considered
- 1 node on bedside table
- 2 nodes on opposite sides of bed

## Decision
2 nodes — one on bedside table (left), one on ledge (right), both at mattress height.

## Reasoning
When sleeping on one side, the body partially blocks the node on that side. A second node on the opposite side ensures at least one node always has a clean signal path to the chest. This is particularly important for breathing detection accuracy during REM sleep when movement is higher. The bed is 1.0-1.2m wide, putting both nodes at 0.5-0.6m from the chest — within the optimal sensing range.

## Consequences
Requires routing a 3-5m USB-C cable along the skirting board from the left-side wall sockets to the right node. Small added complexity, significant reliability improvement.
