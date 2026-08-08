from rolloutplane_viz.models import Point
from rolloutplane_viz.source import downsample


def test_downsample_preserves_endpoints_and_spike() -> None:
    points = [
        Point(timestamp_ns=index, value=100 if index == 500 else float(index % 7), bundle_id="b")
        for index in range(1_000)
    ]
    result = downsample(points, limit=100)
    assert len(result) <= 100
    assert result[0] == points[0]
    assert result[-1] == points[-1]
    assert max(point.value for point in result) == 100
