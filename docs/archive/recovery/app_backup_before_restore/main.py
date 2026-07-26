SampleRate = fromSampleRate;
    this.toSampleRate = toSampleRate;
    this.channels = channels || 0;
    this.inputBufferSize = inputBufferSize;
    this.initialize()
  }

  initialize() {
    if (this.fromSampleRate == this.toSampleRate) {

      // Setup resampler bypass - Resampler just returns what was passed through
      this.resampler = (buffer) => {
        return buffer
      };
      this.ratioWeight = 1;

    } else {
      if (this.fromSampleRate < this.toSampleRate) {

        // Use generic linear interpolation if upsampling,
        // as linear interpolation produces a gradient that we want
        // and works fine with two input sample points per output in this case.
        this.linearInterpolation();
        this.lastWeight = 1;

      } else {

        // Custom resampler I wrote that doesn't skip samples
        // like standard linear interpolation in high downsampling.
        // This is more accurate than linear interpolation on downsampling.
        this.multiTap();
        this.tailExists = false;
        this.lastWeight = 0;
      }

      // Initialize the internal buffer:
      this.initializeBuffers();
      this.ratioWeight = this.fromSampleRate / this.toSampleRate;
    }
  }

  bufferSlice(sliceAmount) {

    //Typed arr