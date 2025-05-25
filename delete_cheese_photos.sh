#!/bin/bash

# Find matching files
files=$(find photos -type f -path "photos/**/cheese_*.jpg" & find photos -type f -path "photos/cheese_*.jpg")

# Check if files were found
if [ -z "$files" ]; then
  echo "No matching files found."
  exit 0
fi

# Show found files
echo "The following files will be deleted:"
echo "$files"
echo

# Ask for confirmation
read -p "Are you sure you want to delete all these files? (y/n): " confirm
if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
  echo "$files" | xargs rm -v
  echo "Files deleted."
else
  echo "Operation cancelled."
fi