# Snap & Shrink: Building and Debugging a Serverless Image Pipeline on AWS

Snap & Shrink is a serverless photo thumbnail generator. Upload a photo to an S3 bucket and, within seconds, a compressed thumbnail appears in a second bucket — no servers, no polling, no manual steps. The architecture is deliberately simple: an S3 upload event triggers an AWS Lambda function (Python 3.12 on arm64), which pulls the original image, resizes it with Pillow to a 300x300 thumbnail, and writes the result to a destination bucket defined by an environment variable. An IAM role scopes the function's permissions to exactly the two buckets it needs.

The interesting part of this project isn't the happy path. It's the two bugs that stood between "deployed" and "working," because both forced me to debug from raw error output rather than follow a tutorial.

## Bug one: the layer that lied about its architecture

Pillow isn't pure Python — its core image engine is compiled C. That means it has to be packaged as a Lambda layer built for the exact runtime and CPU architecture of the function. My function ran on arm64, and I had attached a layer named `pillow-layer-arm64`.

The first end-to-end test produced nothing. The destination bucket stayed empty. Instead of guessing, I went to CloudWatch and pulled the newest log stream. The function had crashed before executing a single line of my code:

```
Runtime.ImportModuleError: Unable to import module 'lambda_function':
cannot import name '_imaging' from 'PIL' (/opt/python/PIL/__init__.py)
```

Reading that error carefully told me three things. Python had found PIL at `/opt/python/PIL/`, so the layer's folder structure was correct. The failure was specifically on `_imaging` — Pillow's compiled binary component. So the pure-Python parts of the layer loaded fine, but the compiled machine code didn't match the environment it was running in. Despite its name, the layer's binaries were not actually built for arm64 Python 3.12. The lesson: a zip file's name proves nothing about its contents.

The fix was to rebuild the layer in a way that made the architecture verifiable rather than assumed. Using AWS CloudShell, I forced pip to download only prebuilt binary wheels for the exact target platform:

```bash
pip install \
  --platform manylinux2014_aarch64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --target pillow-layer/python \
  Pillow
```

The proof was in pip's own output. The wheel it downloaded was `pillow-12.2.0-cp312-cp312-manylinux2014_aarch64.whl` — `cp312` confirming Python 3.12, `aarch64` confirming arm64. I zipped the `python/` directory, published it as version 2 of the layer with `aws lambda publish-layer-version`, swapped the function's layer ARN from `:1` to `:2`, and the next upload produced a thumbnail. This time I wasn't trusting a filename; I had verified the wheel tag before deploying.

## Bug two: the code only worked on lab-perfect filenames

With the pipeline working, I tested it against a hostile input: a file named `my test photo.jpg`, spaces included. This matters because S3 doesn't deliver raw filenames in its event notifications — it URL-encodes them. Spaces arrive as `+`, special characters as percent-encoded sequences. My handler read the object key directly from the event:

```python
file_name = event['Records'][0]['s3']['object']['key']
```

That code would ask S3 for `my+test+photo.jpg`, a file that doesn't exist, and fail with a NoSuchKey error. Any real user uploading photos from a phone or camera would hit this immediately — filenames with spaces are the norm, not the edge case. The fix was small but the principle isn't:

```python
import urllib.parse
file_name = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'])
```

I deployed the patch and re-tested with the spaced filename. The thumbnail landed. The difference between the first passing test and this one is the difference between "it ran once" and "it handles real-world input."

## What I'd say about production readiness

I know what this project is and what it isn't. It's a working, verified, event-driven pipeline. It is not hardened. There's no error handling for non-image uploads — a PDF or corrupt file would make Pillow throw and the invocation would die silently. There's no dead-letter queue, so failed events vanish instead of being captured for retry. And the trigger configuration has to be handled carefully to avoid the classic recursive-invocation trap of a Lambda writing into the bucket that triggers it. Knowing where the line sits between a working prototype and a production system — and being able to name what's missing — was as much the point of this project as the code itself.

## What this project demonstrates

I can stand up event-driven AWS infrastructure from scratch: S3, Lambda, IAM roles, triggers, environment variables, and layers. I can diagnose failures from CloudWatch logs rather than re-running things and hoping. I understand why compiled dependencies must match runtime architecture, and how to build and verify cross-platform packages with pip's platform flags. And I test against hostile inputs before calling something done, because software that only survives clean inputs isn't finished — it's lucky.
