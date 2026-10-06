# platmon in a container. It monitors the host, so it needs the host mounts in compose.yaml
# (plus compose.jetson.yaml on Jetson); see README "Docker".
# Build it yourself; images are not published (the base image contains GPL/LGPL software,
# see README "Container image licensing").
# Plain Python image: platmon only reads /proc and /sys, so no NVIDIA runtime or L4T base is needed.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/platmon
COPY platmon.py platmon.ini ./
COPY collector ./collector
COPY frontends ./frontends

# everything platmon reads in /sys and /proc is world-readable; no root needed
USER 65534:65534
EXPOSE 8080
# /api/stats answers 503 while there is no current data, which marks the container unhealthy.
# Keep [http] port at 8080 inside the container; change the published port instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/stats', timeout=4)"]
ENTRYPOINT ["python3", "/opt/platmon/platmon.py"]
CMD ["/opt/platmon/platmon.ini"]
