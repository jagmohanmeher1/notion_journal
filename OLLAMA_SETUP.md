# Ollama Setup Guide

Ollama is a free, local AI that runs on your computer. No API keys, no costs, completely private!

## Quick Setup

### 1. Install Ollama

**Windows:**
1. Download from https://ollama.com/download/windows
2. Run the installer
3. Ollama will start automatically

**Verify installation:**
```bash
ollama --version
```

### 2. Download a Model

Choose a model based on your needs:

**Recommended (Good balance of speed and quality):**
```bash
ollama pull llama3.2
```

**Smaller/Faster (if you have limited RAM):**
```bash
ollama pull phi3
```

**Better Quality (if you have 16GB+ RAM):**
```bash
ollama pull llama3.1
ollama pull mistral
```

### 3. Test Ollama

```bash
ollama run llama3.2 "Write a short test message"
```

If it works, you're ready!

### 4. Configure the Journal Script

In your `.env` file:
```env
USE_OLLAMA=true
OLLAMA_MODEL=llama3.2
```

That's it! The script will automatically use Ollama for AI reports.

## Model Recommendations

| Model | Size | RAM Needed | Speed | Quality |
|-------|------|------------|-------|---------|
| `phi3` | 3.8GB | 8GB | ⚡⚡⚡ Fast | ⭐⭐ Good |
| `llama3.2` | 2.0GB | 8GB | ⚡⚡⚡ Fast | ⭐⭐⭐ Very Good |
| `llama3.1` | 4.7GB | 16GB | ⚡⚡ Medium | ⭐⭐⭐⭐ Excellent |
| `mistral` | 4.1GB | 16GB | ⚡⚡ Medium | ⭐⭐⭐⭐ Excellent |

**For most users**: `llama3.2` is the best choice - fast, good quality, small size.

## Troubleshooting

### "Ollama not available" error

1. Make sure Ollama is running:
   ```bash
   ollama list
   ```

2. If it says "connection refused", start Ollama:
   - Windows: Check if Ollama service is running in Task Manager
   - Or restart your computer

### Model not found

Make sure you downloaded the model:
```bash
ollama pull llama3.2
```

### Slow generation

- Use a smaller model like `phi3` or `llama3.2`
- Close other applications to free up RAM
- The first generation is always slower (model loading)

## Benefits of Ollama

✅ **100% Free** - No API costs ever  
✅ **Completely Private** - All data stays on your computer  
✅ **Works Offline** - No internet needed after setup  
✅ **Fast** - Runs locally, no network latency  
✅ **No Limits** - Generate as many reports as you want  

## Advanced: Custom Models

You can use any Ollama-compatible model:

```bash
ollama pull codellama    # For code-focused analysis
ollama pull neural-chat  # For conversational reports
```

Then update `.env`:
```env
OLLAMA_MODEL=codellama
```
