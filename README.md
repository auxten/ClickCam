# ClickCam

A real-time camera interaction application that uses AI to analyze video frames and provide responses. The application includes image similarity detection to optimize AI calls and event logging for historical analysis.

## Special Thanks

This project is largely based on and reuses code from [smolvlm-realtime-webcam](https://github.com/ngxson/smolvlm-realtime-webcam) by [ngxson](https://github.com/ngxson). We extend our sincere gratitude for their excellent work and contribution to the open-source community.

## Demo

![Demo](/demo.png)

## Features

- Real-time camera feed processing
- AI-powered image analysis using llama-server
- Image similarity detection to reduce redundant AI calls
- Event logging with [chDB (ClickHouse in-process)](https://github.com/chdb-io/chdb)
- Web interface with live updates
- Configurable processing intervals
- CORS support for cross-origin requests

## Prerequisites

- Python 3.11 or higher
- llama-server with SmolVLM model
- ClickHouse database (chdb)
- Web browser with camera access

## Installation

1. Install Python dependencies:
    ```bash
    pip install -r requirements.txt
    ```
1. Install [llama-server](https://github.com/ggml-org/llama.cpp/blob/master/docs/install.md)


## Usage

1. Start the server:
    ```bash
    python server.py
    ```
    Model [ggml-org/SmolVLM-500M-Instruct-GGUF](https://huggingface.co/ggml-org/SmolVLM-500M-Instruct-GGUF) will be downloaded automatically
2. Open `index.html` in your web browser
3. Grant camera permissions when prompted
4. Click "Start" to begin processing
5. View real-time AI responses and event history

## Configuration

### Server Settings

- `HASH_THRESHOLD`: Controls image similarity sensitivity (default: 5)
  - Higher values = more sensitive (requires larger changes to trigger new analysis)
  - Lower values = less sensitive (smaller changes will trigger new analysis)

- Database: Events are stored in `events.db` using ClickHouse
  - Events include timestamp and AI response content
  - Recent events are displayed in the web interface

### Web Interface Settings

- Processing Interval: Choose between 100ms to 2s
- Base API URL: Configure the server endpoint
- Instruction: Customize the prompt for AI analysis

## Architecture

### Components

1. **Server (server.py)**
   - Manages llama-server process
   - Handles image similarity detection
   - Stores events in ClickHouse database
   - Provides API endpoints for web interface

2. **Web Interface (index.html)**
   - Displays camera feed
   - Shows AI responses
   - Lists recent events
   - Provides control interface

### Data Flow

1. Camera captures frame
2. Image similarity check against previous frame
3. If different enough:
   - Send to llama-server for analysis
   - Store response in database
   - Update web interface
4. If too similar:
   - Reuse previous response
   - Skip llama-server call

## Event Logging

Events are stored in a ClickHouse database with the following structure:
- `id`: Unique identifier
- `timestamp`: Event time
- `content`: AI response content

Events are displayed in the web interface, showing the 20 most recent entries.

## Performance Optimization

- Image similarity detection reduces unnecessary AI calls
- Configurable processing intervals
- Efficient event storage and retrieval
- Automatic cleanup of resources

## Error Handling

- Camera access errors
- Server connection issues
- Image processing errors
- Database operation errors

All errors are logged and displayed in the web interface when appropriate.

## Contributing

Feel free to submit issues and enhancement requests!
