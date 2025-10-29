#!/bin/bash
# Script to split all mp3 files in a given directory into 15-second chunks using ffmpeg

# Check if a directory is provided
if [ -z "$1" ]; then
  echo "Usage: $0 <directory>"
  exit 1
fi

DIRECTORY=$1

# Loop through all mp3 files in the directory
for file in "$DIRECTORY"/*.mp3
  do
    # Get the base filename without the .mp3 extension
    base=$(basename "$file" .mp3)
    
    # Use ffmpeg to split the file into 15-second segments
    # -i: input file
    # -f segment: specifies the segment format
    # -segment_time 15: sets the duration of each chunk to 15 seconds
    # -c copy: copies the stream without re-encoding, which is fast and preserves quality
    # The output filename is patterned to include the original name and a chunk number
    ffmpeg -i "$file" -f segment -segment_time 15 -c copy "$DIRECTORY/${base}_chunk%03d.mp3"
  done

echo "Finished splitting files in $DIRECTORY."
