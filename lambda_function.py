import boto3
import os
from PIL import Image
import io
import urllib.parse
s3 = boto3.client('s3')

def lambda_handler(event, context):
    source_bucket = event['Records'][0]['s3']['bucket']['name']
    file_name = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'])
    dest_bucket = os.environ['THUMBNAIL_BUCKET']
    
    print(f"New photo uploaded: {file_name}")
    
    response = s3.get_object(Bucket=source_bucket, Key=file_name)
    image_data = response['Body'].read()
    
    image = Image.open(io.BytesIO(image_data))
    image.thumbnail((300, 300))
    
    buffer = io.BytesIO()
    image_format = image.format or 'JPEG'
    image.save(buffer, format=image_format)
    buffer.seek(0)
    
    thumbnail_key = f"thumbnail-{file_name}"
    s3.put_object(
        Bucket=dest_bucket,
        Key=thumbnail_key,
        Body=buffer,
        ContentType=f'image/{image_format.lower()}'
    )
    
    print(f"Done! Thumbnail saved as: {thumbnail_key}")
    return {'statusCode': 200, 'body': f'Thumbnail created: {thumbnail_key}'}
