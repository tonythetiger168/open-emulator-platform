// 4-bit majority (reconvergent fanout) benchmark: y <= maj(a,b,c) ^ d
module maj4(clk, a, b, c, d, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  input [3:0] c;
  input [3:0] d;
  output reg [3:0] y;
  wire [3:0] ab;
  wire [3:0] ac;
  wire [3:0] bc;
  wire [3:0] maj;
  assign ab = a & b;
  assign ac = a & c;
  assign bc = b & c;
  assign maj = ab | ac | bc;
  always @(posedge clk) begin
    y <= maj ^ d;
  end
endmodule
