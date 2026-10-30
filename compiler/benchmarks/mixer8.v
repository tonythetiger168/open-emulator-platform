// 8-bit bitwise mask-mux benchmark: y <= (a & m) | (b & ~m)
module mixer8(clk, a, b, m, y);
  input clk;
  input [7:0] a;
  input [7:0] b;
  input [7:0] m;
  output reg [7:0] y;
  wire [7:0] lo;
  wire [7:0] hi;
  assign lo = a & m;
  assign hi = b & ~m;
  always @(posedge clk) begin
    y <= lo | hi;
  end
endmodule
